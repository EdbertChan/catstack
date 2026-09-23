from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import detect

sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))
import inbox
from judge_test_base import JudgeTestCase


PYTHON = sys.executable
HAND_BACK = "Please run: invoker-cli setup slack ... then tell me when it completes."
XCODE_HAND_BACK = "Simulator build still passes. Now on your end in Xcode:"
PERMISSION_HAND_BACK = "The sandbox refused that command. Please run it on your machine."
OAUTH_HAND_BACK = "Please finish the OAuth consent in your browser, then tell me when it completes."
ATTEMPTED_HAND_BACK = "I ran the setup command and it needs you to finish the browser login."
HIT_ANSWER = json.dumps({"match": True, "closest": HAND_BACK})
CLEAN_ANSWER = json.dumps({"match": False, "closest": ""})
HIT_RUNNER = ["fake", [PYTHON, "-c", f"print({HIT_ANSWER!r})", "{prompt}"]]
CLEAN_RUNNER = ["fake", [PYTHON, "-c", f"print({CLEAN_ANSWER!r})", "{prompt}"]]
SELECTIVE_SCRIPT = "import json,sys; text=sys.argv[-1].lower().split('text:\\n',1)[-1]; clean=any(value in text for value in ('permission denied', 'oauth consent', 'browser login', 'i ran the setup command', 'ran the command successfully')); print(json.dumps({'match': not clean, 'closest': ''}))"
SELECTIVE_RUNNER = ["selective", [PYTHON, "-c", SELECTIVE_SCRIPT, "{prompt}"]]
MISSING_RUNNER = ["missing", ["catstack-handback-no-such-runner", "{prompt}"]]


def row(role: str, content: object) -> str:
    if role == "tool_use":
        message = {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "tool_use", **content}]},
        }
    elif role == "tool_result":
        message = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "tool_result", "content": content}]},
            "toolUseResult": {"stdout": content},
        }
    else:
        message = {"type": role, "message": {"role": role, "content": [{"type": "text", "text": content}]}}
    return json.dumps(message)


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.hook_state = tempfile.TemporaryDirectory()
        self.state_patch = patch.dict(os.environ, {"HANDBACK_NEEDS_ATTEMPT_STATE_DIR": self.hook_state.name})
        self.state_patch.start()
        detect.STATE_DIR = self.hook_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while os.path.isdir(os.path.join(self.state.name, "jobs")) and os.listdir(os.path.join(self.state.name, "jobs")) and time.monotonic() < deadline:
            time.sleep(0.1)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        self.state_patch.stop()
        self.hook_state.cleanup()
        super().tearDown()

    def transcript(self, reply: str, result: str = "") -> str:
        path = os.path.join(self.hook_state.name, "session.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(row("user", "Set up the requested integration.") + "\n")
            if result:
                handle.write(row("tool_use", {"name": "Bash", "input": {"command": "invoker-cli setup slack"}}) + "\n")
                handle.write(row("tool_result", result) + "\n")
            handle.write(row("assistant", reply) + "\n")
        return path

    def queue(self, reply: str, result: str = "", runner=None):
        path = self.transcript(reply, result)
        self.use_runners(runner or SELECTIVE_RUNNER)
        job_id = detect.enqueue_judge({"transcript_path": path, "last_assistant_message": reply})
        return path, job_id

    def messages(self, path: str) -> list[str]:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            found = inbox.messages(path)
            if found:
                return found
            time.sleep(0.1)
        return []

    def wait_done(self, path: str, seconds: float = 5) -> list[str]:
        deadline = time.monotonic() + seconds
        jobs_path = os.path.join(self.state.name, "jobs")
        while time.monotonic() < deadline:
            if not os.path.isdir(jobs_path) or not os.listdir(jobs_path):
                return inbox.messages(path)
            time.sleep(0.05)
        return inbox.messages(path)

    def test_handback_without_attempt_flags(self):
        path, job_id = self.queue(HAND_BACK)
        self.assertIsNotNone(job_id)
        self.assertIn("handback", self.messages(path)[0])

    def test_xcode_handback_without_attempt_flags(self):
        path, job_id = self.queue(XCODE_HAND_BACK)
        self.assertIsNotNone(job_id)
        self.assertIn("handback", self.messages(path)[0])

    def test_permission_denial_handback_is_silent(self):
        path, job_id = self.queue(PERMISSION_HAND_BACK, "Permission denied by sandbox classifier", CLEAN_RUNNER)
        self.assertIsNotNone(job_id)
        self.assertEqual(self.wait_done(path), [])

    def test_oauth_consent_handback_is_silent(self):
        path, job_id = self.queue(OAUTH_HAND_BACK, runner=CLEAN_RUNNER)
        self.assertIsNotNone(job_id)
        self.assertEqual(self.wait_done(path), [])

    def test_attempted_handback_is_silent(self):
        path, job_id = self.queue(ATTEMPTED_HAND_BACK, "setup completed but browser consent is required", CLEAN_RUNNER)
        self.assertIsNotNone(job_id)
        self.assertEqual(self.wait_done(path), [])

    def test_judge_failure_is_unchecked(self):
        path, job_id = self.queue(HAND_BACK, runner=MISSING_RUNNER)
        self.assertIsNotNone(job_id)
        self.assertIn("could not judge", self.messages(path)[0])

    def test_second_stop_with_stop_hook_active_is_silent(self):
        path = self.transcript(HAND_BACK)
        self.use_runners(SELECTIVE_RUNNER)
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "last_assistant_message": HAND_BACK, "stop_hook_active": True}))

    def test_judge_prompt_contains_reply_and_tool_exchange(self):
        path = self.transcript(HAND_BACK, "Permission denied")
        self.use_runners(SELECTIVE_RUNNER)
        captured = {}

        class Judge:
            def enqueue(self, job):
                captured["job"] = job
                return "captured"

        with patch.object(detect, "_judge", return_value=Judge()):
            job_id = detect.enqueue_judge({"transcript_path": path, "last_assistant_message": HAND_BACK})
        self.assertIsNotNone(job_id)
        self.assertIn(HAND_BACK, captured["job"]["prompt"])
        self.assertIn("invoker-cli setup slack", captured["job"]["prompt"])
        self.assertIn("Permission denied", captured["job"]["prompt"])

    def test_clean_input_does_not_flag(self):
        path, job_id = self.queue("I ran the command successfully and verified the result.", runner=CLEAN_RUNNER)
        self.assertIsNotNone(job_id)
        self.assertEqual(self.wait_done(path), [])

    def test_unreadable_transcript_is_unchecked(self):
        self.use_runners(HIT_RUNNER)
        path = os.path.join(self.hook_state.name, "missing.jsonl")
        err = __import__("io").StringIO()
        with patch("sys.stderr", err):
            job_id = detect.enqueue_judge({"transcript_path": path, "last_assistant_message": HAND_BACK})
        self.assertIsNone(job_id)
        self.assertIn("unchecked", err.getvalue())
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
