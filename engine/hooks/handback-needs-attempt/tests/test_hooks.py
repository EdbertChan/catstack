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
sys.path.insert(0, HOOK_DIR)
import claude_stop_check
import detect
sys.path.append(os.path.join(os.path.dirname(HOOK_DIR), "_flags"))
import flags
sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox
from judge_test_base import JudgeTestCase

PY = sys.executable
HIT = json.dumps({"match": True, "closest": "Please run the setup command"})
CLEAN = json.dumps({"match": False, "closest": ""})


def row(role, content, **extra):
    data = {"type": role, "message": {"role": role, "content": content}}
    data.update(extra)
    return data


def tool_use(command):
    return row("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": command}}])


def tool_result(content, **extra):
    return row("user", [{"type": "tool_result", "content": content}], **extra)


class TestLocalDecision(unittest.TestCase):
    def test_flags_without_attempt(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": "Please run: invoker-cli setup slack ... then tell me when it completes",
            "transcript_lines": [row("user", "set up Slack")],
        }))

    def test_flags_xcode_handback_without_attempt(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": "Simulator build still passes. Now on your end in Xcode:",
            "transcript_lines": [row("user", "build the app")],
        }))

    def test_permission_denial_is_silent(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": "Please run the setup on your end.",
            "transcript_lines": [
                row("user", "set it up"),
                tool_use("invoker-cli setup slack"),
                tool_result("permission denied", toolUseResult={"permissionDenied": True}),
            ],
        }))

    def test_oauth_consent_is_sent_to_judge(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": "Please approve the OAuth consent in your browser, then tell me when it completes.",
            "transcript_lines": [row("user", "connect Slack")],
        }))

    def test_unreadable_transcript_is_unchecked(self):
        err = io.StringIO()
        self.assertIsNone(detect.enqueue_judge({
            "last_assistant_message": "Please run the setup command.",
            "transcript_path": "/nonexistent/handback.jsonl",
            "cwd": tempfile.gettempdir(),
        }, stderr=err))
        self.assertIn("unchecked", err.getvalue())

    def test_stop_hook_active_is_silent(self):
        self.assertIsNone(detect.decide({"stop_hook_active": True, "last_assistant_message": "Please run it."}))


class TestJudgeEnqueue(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.work.name, "session.jsonl")
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
        path = os.path.join(self.state.name, "jobs")
        return os.listdir(path) if os.path.isdir(path) else []

    def write(self, lines):
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")

    def payload(self, reply):
        return {"last_assistant_message": reply, "transcript_path": self.transcript, "cwd": self.work.name}

    def test_hit_reaches_inbox(self):
        self.use_runners(["fake", [PY, "-c", f"print({HIT!r})", "{prompt}"]])
        self.write([row("user", "set up Slack")])
        self.assertIsNotNone(detect.enqueue_judge(self.payload("Please run: invoker-cli setup slack ... then tell me when it completes")))
        deadline = time.monotonic() + 15
        messages = []
        while time.monotonic() < deadline and not messages:
            messages = judge_inbox.messages(self.transcript)
            time.sleep(0.1)
        self.assertTrue(any("handback-needs-attempt" in message for message in messages), messages)

    def test_judge_failure_is_unchecked(self):
        self.use_runners(["missing", ["catstack-no-such-judge", "{prompt}"]])
        self.write([row("user", "set up Slack")])
        self.assertIsNotNone(detect.enqueue_judge(self.payload("Please run the setup command.")))
        deadline = time.monotonic() + 15
        messages = []
        while time.monotonic() < deadline and not messages:
            messages = judge_inbox.messages(self.transcript)
            time.sleep(0.1)
        self.assertTrue(any("could not judge" in message for message in messages), messages)


class TestClaudeEntrypoint(unittest.TestCase):
    def test_malformed_stdin_is_unchecked(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")), redirect_stderr(err):
            claude_stop_check.main()
        self.assertIn("unchecked", err.getvalue())


if __name__ == "__main__":
    unittest.main()
