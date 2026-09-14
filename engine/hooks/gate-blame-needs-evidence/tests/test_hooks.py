#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
HOOKS_DIR = os.path.dirname(HOOK_DIR)
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(HOOKS_DIR, "llm-judge"))

import claude_stop_check
import detect
import inbox as judge_inbox
import install_claude_hook
import phrases
from judge_test_base import JudgeTestCase

with open(os.path.join(FIXTURES, "real_session.json"), encoding="utf-8") as handle:
    REAL = json.load(handle)

BLAME = "I ran /reflect and automate-me, so scope-lock should be gone. Its clear condition was met and it still fires."
PRONOUN = "You typed both commands. It still fires."
CLEAN = "scope-lock is not broken; it was working as written."
PY = sys.executable
JUDGE_HIT = json.dumps({"match": True, "closest": BLAME})
JUDGE_CLEAN = json.dumps({"match": False, "closest": ""})


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


def tool_read(path: str, is_error: bool = False) -> list[str]:
    tool_id = "read-1"
    return [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Read", "input": {"file_path": path}}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": "..."}]}}),
    ]


class TestGateBlameNeedsEvidence(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.use_runners(("fake", [PY, "-c", f"print({JUDGE_HIT!r})", "{{prompt}}"]))
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, *lines: str, name: str = "session.jsonl") -> str:
        path = os.path.join(self.work.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    def wait_for_messages(self, path: str) -> list[str]:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            messages = judge_inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.1)
        return []

    def queue(self, reply: str, *lines: str) -> str:
        path = self.write_transcript(*lines, transcript_line("assistant", reply))
        self.assertIsNotNone(detect.enqueue_judge({"last_assistant_message": reply, "transcript_path": path}))
        return path

    def test_dictionary_loads(self):
        self.assertEqual(phrases.load("gate-blame-needs-evidence")["checker"], "gate-blame-needs-evidence")

    def test_queues_when_reply_names_unread_gate(self):
        path = self.queue(BLAME)
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(len(self.wait_for_messages(path)), 1)

    def test_queues_pronoun_after_unread_tool_refusal(self):
        refusal = json.dumps({"type": "user", "message": {"content": "hook error: [hooks/scope-lock/detect.py]"}})
        self.queue(PRONOUN, refusal)
        self.assertEqual(len(self.jobs()), 1)

    def test_does_not_queue_after_successful_read_or_citation_or_without_gate(self):
        cases = (
            (BLAME, tool_read("engine/hooks/scope-lock/detect.py")),
            ("scope-lock is broken; see detect.py:159", []),
            ("The nightly build is broken again.", []),
        )
        for index, (reply, lines) in enumerate(cases):
            path = self.write_transcript(*lines, transcript_line("assistant", reply), name=f"case-{index}.jsonl")
            self.assertIsNone(detect.enqueue_judge({"last_assistant_message": reply, "transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_hit_verdict_reaches_agent_with_gate_name(self):
        path = self.queue(BLAME)
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("scope-lock", messages[0])
        self.assertIn(os.path.join(HOOKS_DIR, "scope-lock", "detect.py"), messages[0])

    def test_clean_verdict_says_nothing(self):
        self.use_runners(("fake", [PY, "-c", f"print({JUDGE_CLEAN!r})", "{{prompt}}"]))
        path = self.queue(CLEAN)
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_unchecked_verdict_says_could_not_judge(self):
        self.use_runners(("missing", ["no-such-judge", "{{prompt}}"]))
        path = self.queue(BLAME)
        self.assertIn("could not judge", self.wait_for_messages(path)[0])

    def test_unreadable_transcript_queues_nothing_and_writes_unchecked(self):
        err = io.StringIO()
        with redirect_stderr(err):
            detect.try_enqueue_judge({"last_assistant_message": BLAME, "transcript_path": "/missing/session.jsonl"})
        self.assertEqual(self.jobs(), [])
        self.assertIn("unchecked", err.getvalue())

    def test_stop_hook_active_queues_nothing(self):
        with patch.object(detect, "enqueue_judge") as enqueue:
            detect.try_enqueue_judge({"stop_hook_active": True})
        enqueue.assert_not_called()

    def test_stop_entry_always_exits_zero(self):
        path = self.write_transcript(transcript_line("assistant", BLAME))
        with patch.object(sys, "stdin", io.StringIO(json.dumps({"last_assistant_message": BLAME, "transcript_path": path}))):
            claude_stop_check.main()
        self.assertEqual(len(self.jobs()), 1)

    def test_real_session_fires_queue_and_read_cases_do_not(self):
        for case in REAL["fires"]:
            lines = [json.dumps(line) for line in REAL["blocked_read"]]
            path = self.write_transcript(*lines, transcript_line("assistant", case["reply"]), name=f"fire-{case['label']}.jsonl")
            self.assertIsNotNone(detect.enqueue_judge({"last_assistant_message": case["reply"], "transcript_path": path}))
        for index, case in enumerate((REAL["silent_after_review_unit_read"], REAL["silent_after_agent_routing_guard_read"])):
            lines = [json.dumps(line) for line in case["transcript"]]
            path = self.write_transcript(*lines, transcript_line("assistant", case["reply"]), name=f"silent-{index}.jsonl")
            self.assertIsNone(detect.enqueue_judge({"last_assistant_message": case["reply"], "transcript_path": path}))


class TestInstallWiresStopOnly(unittest.TestCase):
    def test_manifest_wires_stop_and_never_a_tool_event(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        self.assertEqual(set(fragment["hooks"]), {"Stop"})
        command = fragment["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("gate-blame-needs-evidence/claude_stop_check.py", command)

    def test_merge_is_idempotent_and_keeps_other_hooks(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        other = {"matcher": "*", "hooks": [{"type": "command", "command": "python3 other/x.py"}]}
        settings = {"hooks": {"Stop": [other]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        self.assertEqual(settings["hooks"]["Stop"][0], other)
        self.assertEqual(len(settings["hooks"]["Stop"]), 2)


if __name__ == "__main__":
    unittest.main()
