#!/usr/bin/env python3
"""Tests for the user-did-it UserPromptSubmit hook.

Run: python3 -m unittest discover -s engine/hooks/user-did-it/tests -v

Whether the user did a step by hand is judged by the background model, so
these tests pin the local half: which prompts are sent to the judge, that the
reflect-enforcement flag gates it, that an unreadable payload is reported as
unchecked, and that a judge hit reaches the llm-judge inbox. No test calls a
real model.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
sys.path.append(os.path.join(os.path.dirname(HOOK_DIR), "_flags"))
import flags  # noqa: E402
import inbox as judge_inbox  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": "ran it in my terminal"})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]

PASTED_RUN = (
    "I don't know why you don't do this yourself but edbertchan@MacBookPro Invoker %  "
    "bash \"/private/tmp/claude-501/scratchpad/revert-db-reaper-retention.sh\"\n"
    "Backing up current (aggressive) config.json"
)
TASK_NOTIFICATION = "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"
STOP_FEEDBACK = "Stop hook feedback:\n[python3 diu-stop/claude_stop_check.py]: Apply diu: 232 words"
CONTINUED = "This session is being continued from a previous conversation that ran out of context."


class TestIsPerson(unittest.TestCase):
    def test_pasted_terminal_run_is_the_person(self):
        self.assertTrue(detect.is_person(PASTED_RUN))

    def test_machine_relays_stay_silent(self):
        for text in (TASK_NOTIFICATION, STOP_FEEDBACK, CONTINUED, "[SYSTEM NOTIFICATION - NOT USER INPUT]", "   "):
            self.assertFalse(detect.is_person(text), text)


class TestEnqueue(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": PASTED_RUN}}) + "\n")
        self.flag_env = patch.dict(os.environ, {"HOME": self.work.name, flags.REFLECT_ENFORCEMENT: "1"})
        self.flag_env.start()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.flag_env.stop()
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self):
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def payload(self, prompt):
        return {"prompt": prompt, "transcript_path": self.transcript, "cwd": self.work.name}

    def run_hook(self, stdin_text):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(stdin_text)), patch.object(sys, "stderr", err):
            try:
                claude_prompt_submit.main()
            except SystemExit as exc:
                self.fail(f"hook exited with {exc.code}; it must never block")
        return err.getvalue()

    def test_fires_on_bad_case_pasted_terminal_run_enqueues_one_job(self):
        err = self.run_hook(json.dumps(self.payload(PASTED_RUN)))
        self.assertNotIn("catstack-hook", err)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self.jobs():
            time.sleep(0.05)
        with open(os.path.join(self.state.name, "jobs", self.jobs()[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertEqual(job["hook"], "user-did-it")
        self.assertIn("revert-db-reaper-retention.sh", job["prompt"])

    def test_fires_judge_hit_is_delivered_through_the_inbox(self):
        self.use_runners(ANSWERS_HIT)
        self.assertIsNotNone(detect.enqueue_judge(self.payload(PASTED_RUN)))
        deadline = time.monotonic() + 15
        got = []
        while time.monotonic() < deadline and not got:
            got = judge_inbox.messages(self.transcript)
            time.sleep(0.1)
        self.assertTrue(any("user-did-it" in message for message in got), got)

    def test_stays_silent_on_clean_case_machine_relay(self):
        for text in (TASK_NOTIFICATION, STOP_FEEDBACK, CONTINUED):
            self.assertIsNone(detect.enqueue_judge(self.payload(text)), text)
        self.assertEqual(self.jobs(), [])

    def test_stays_silent_when_reflect_enforcement_is_off(self):
        with patch.dict(os.environ, {"HOME": self.work.name}):
            os.environ.pop(flags.REFLECT_ENFORCEMENT, None)
            self.assertIsNone(detect.enqueue_judge(self.payload(PASTED_RUN)))
        self.assertEqual(self.jobs(), [])

    def test_missing_prompt_is_reported_unchecked_not_clean(self):
        err = io.StringIO()
        self.assertIsNone(detect.enqueue_judge({"transcript_path": self.transcript, "cwd": self.work.name}, stderr=err))
        self.assertIn("catstack-hook-unchecked user-did-it", err.getvalue())
        self.assertEqual(self.jobs(), [])

    def test_malformed_stdin_is_reported_unchecked(self):
        err = self.run_hook("not json")
        self.assertIn("catstack-hook-unchecked user-did-it", err)
        self.assertEqual(self.jobs(), [])

    def test_unreadable_dictionary_is_reported_not_silent(self):
        with patch.object(detect, "PHRASES_PATH", "/nonexistent/phrases.py"):
            detect._phrases.cache_clear()
            err = self.run_hook(json.dumps(self.payload(PASTED_RUN)))
        self.assertIn("catstack-hook-error user-did-it", err)


if __name__ == "__main__":
    unittest.main()
