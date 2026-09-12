#!/usr/bin/env python3
"""Tests for wrong-check-reflect."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import judge  # noqa: E402
import phrases  # noqa: E402


PY = sys.executable
HIT_TEXT = "Correction: the file I pointed you to earlier is not the one in use; the real one is src/b.py."
OPTION_TEXT = "You're right. Let's go with option B."
COUNT_TEXT = "I double-checked my earlier count and it holds; nothing in it was wrong."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": HIT_TEXT})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
SLOW_CLEAN = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def run_cursor(payload: dict) -> tuple[dict, str]:
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out), redirect_stderr(err):
            cursor_session.main()
    return json.loads(out.getvalue() or "{}"), err.getvalue()


def run_codex_notify(argv: list[str]) -> str:
    err = io.StringIO()
    with patch.object(sys, "argv", ["codex_notify.py", *argv]):
        with redirect_stderr(err):
            codex_notify.main()
    return err.getvalue()


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


class TestWrongCheckReflect(unittest.TestCase):
    def setUp(self):
        self.reflect_state = tempfile.TemporaryDirectory()
        self.judge_state = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "WRONG_CHECK_REFLECT_STATE_DIR": self.reflect_state.name,
            judge.STATE_ENV: self.judge_state.name,
            judge.RUNNERS_ENV: json.dumps([ANSWERS_HIT]),
        })
        self.env.start()
        os.environ.pop(judge.CHILD_ENV, None)
        detect.STATE_DIR = self.reflect_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.env.stop()
        self.judge_state.cleanup()
        self.reflect_state.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.judge_state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, *lines: tuple[str, str], name: str = "session.jsonl") -> str:
        path = os.path.join(self.reflect_state.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for role, text in lines:
                handle.write(transcript_line(role, text) + "\n")
        return path

    def wait_for_jobs(self, count: int, seconds: float = 5) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                return jobs
            time.sleep(0.05)
        return self.jobs()

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            got = judge_inbox.messages(path)
            if got:
                return got
            time.sleep(0.1)
        return []

    def test_dictionary_loads(self):
        dictionary = phrases.load("wrong-check-reflect")
        self.assertEqual(dictionary["checker"], "wrong-check-reflect")
        self.assertEqual(dictionary["on_hit"], detect.FOLLOWUP)

    def test_decide_no_longer_returns_pattern_hit(self):
        self.assertIsNone(detect.decide({"last_assistant_message": HIT_TEXT}))

    def test_claude_stop_queues_job_for_normal_reply(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([SLOW_CLEAN])
        path = self.write_transcript(("assistant", HIT_TEXT))
        blocked, err = run_claude({"transcript_path": path})
        self.assertFalse(blocked)
        self.assertEqual(err, "")
        jobs = self.wait_for_jobs(1)
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.judge_state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertEqual(job["hook"], "wrong-check-reflect")
        self.assertEqual(job["transcript"], path)
        self.assertEqual(job["on_hit"], detect.FOLLOWUP)

    def test_hit_verdict_reaches_agent_as_dictionary_on_hit(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.wait_for_messages(path), [detect.FOLLOWUP])

    def test_clean_verdict_says_nothing(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([ANSWERS_CLEAN])
        path = self.write_transcript(("assistant", OPTION_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_unchecked_verdict_says_could_not_judge(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([MISSING])
        path = self.write_transcript(("assistant", COUNT_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_judge_not_enqueued_when_stop_hook_active(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "stop_hook_active": True}))
        self.assertEqual(self.jobs(), [])

    def test_judge_not_enqueued_when_already_prompted(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        detect.mark_prompted(path)
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_judge_not_enqueued_when_user_already_asked_reflect(self):
        path = self.write_transcript(("user", "please /reflect"), ("assistant", HIT_TEXT))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_claude_malformed_stdin_fail_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_cursor_returns_empty_followup(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        body, err = run_cursor({"transcript_path": path})
        self.assertEqual(body, {"followup_message": ""})
        self.assertEqual(err, "")

    def test_codex_still_chains(self):
        chain = os.path.join(self.reflect_state.name, "chain.sh")
        marker = os.path.join(self.reflect_state.name, "chained")
        with open(chain, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\necho ok > {marker}\n")
        os.chmod(chain, 0o755)
        payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": HIT_TEXT})
        run_codex_notify([chain, payload])
        self.assertTrue(os.path.isfile(marker))

    def test_judge_enqueue_failure_leaves_reply_untouched(self):
        payload = {"last_assistant_message": HIT_TEXT, "type": "agent-turn-complete", "last-assistant-message": HIT_TEXT}
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("boom")):
            blocked, err = run_claude(payload)
            body, cursor_err = run_cursor(payload)
            codex_err = run_codex_notify([json.dumps(payload)])
        self.assertFalse(blocked)
        self.assertEqual(err, "")
        self.assertEqual(body, {"followup_message": ""})
        self.assertEqual(cursor_err, "")
        self.assertEqual(codex_err, "")


class TestSubagentTranscript(unittest.TestCase):
    def test_resolve_transcript_prefers_agent_transcript_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parent = os.path.join(tmp.name, "session.jsonl")
        agent = os.path.join(tmp.name, "agent-a0231adb57400d820.jsonl")
        for path in (parent, agent):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("")
        self.assertEqual(
            detect.resolve_transcript({"transcript_path": parent, "agent_transcript_path": agent}),
            agent,
        )
        self.assertEqual(detect.resolve_transcript({"transcript_path": parent}), parent)

    def test_missing_agent_transcript_does_not_fall_back_to_the_parent(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parent = os.path.join(tmp.name, "session.jsonl")
        with open(parent, "w", encoding="utf-8") as handle:
            handle.write("")
        gone = os.path.join(tmp.name, "agent-gone.jsonl")
        self.assertEqual(
            detect.resolve_transcript({"transcript_path": parent, "agent_transcript_path": gone}),
            "",
        )


class TestCodexInstaller(unittest.TestCase):
    def test_compute_notify_update_prepends(self):
        from install_codex_notify import compute_notify_update

        text = 'notify = ["python3", "/home/x/.codex/hooks/diu-stop/codex_notify.py"]\n'
        new_text, changed, _ = compute_notify_update(
            text, "/home/x/.codex/hooks/wrong-check-reflect/codex_notify.py"
        )
        self.assertTrue(changed)
        self.assertIn("wrong-check-reflect/codex_notify.py", new_text)
        self.assertIn("diu-stop/codex_notify.py", new_text)
        self.assertLess(
            new_text.index("wrong-check-reflect"),
            new_text.index("diu-stop"),
        )


if __name__ == "__main__":
    unittest.main()
