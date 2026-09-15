from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check
import detect

sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))
import inbox as judge_inbox
from judge_test_base import JudgeTestCase


PY = sys.executable
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": "handback"})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def load_fixture():
    with open(os.path.join(FIXTURES, "handbacks.json"), encoding="utf-8") as handle:
        return json.load(handle)


def transcript_for(case, root):
    lines = [
        {"type": "user", "message": {"role": "user", "content": "finish the setup"}}
    ]
    for index, event in enumerate(case["events"], start=1):
        lines.extend([
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": f"tool-{index}",
                        "name": "Bash",
                        "input": {"command": event["command"]},
                    }],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": f"tool-{index}",
                        "is_error": event["is_error"],
                        "content": event["result"],
                    }],
                },
            },
        ])
    path = os.path.join(root, f"{case['label'].replace(' ', '-')}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


def run_claude(payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            claude_stop_check.main()
    return err.getvalue()


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.hook_state = tempfile.TemporaryDirectory()
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
        self.hook_state.cleanup()
        super().tearDown()

    def wait_for_messages(self, path):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            messages = judge_inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.1)
        return []

    def wait_for_completion(self, path):
        deadline = time.monotonic() + 5
        jobs = os.path.join(self.state.name, "jobs")
        while time.monotonic() < deadline and os.path.isdir(jobs) and os.listdir(jobs):
            time.sleep(0.1)
        return judge_inbox.messages(path)

    def judge_case(self, case, runners):
        path = transcript_for(case, self.hook_state.name)
        self.use_runners(*runners)
        self.assertEqual(run_claude({
            "last_assistant_message": case["reply"],
            "transcript_path": path,
        }), "")
        return path

    def test_flag_command_handback_without_attempt(self):
        case = load_fixture()["fires"][0]
        path = self.judge_case(case, [ANSWERS_HIT])
        self.assertEqual(self.wait_for_messages(path), [detect.ON_HIT])

    def test_flag_xcode_handback_without_attempt(self):
        case = load_fixture()["fires"][1]
        path = self.judge_case(case, [ANSWERS_HIT])
        self.assertEqual(self.wait_for_messages(path), [detect.ON_HIT])

    def test_silent_after_permission_denial(self):
        case = load_fixture()["silent"][0]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_after_sandbox_refusal(self):
        case = load_fixture()["silent"][1]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_after_classifier_refusal(self):
        case = load_fixture()["silent"][2]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_for_oauth_consent(self):
        case = load_fixture()["silent"][3]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_for_human_password_step(self):
        case = load_fixture()["silent"][4]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_after_successful_attempt(self):
        case = load_fixture()["silent"][5]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_silent_for_quoted_reference(self):
        case = load_fixture()["silent"][6]
        path = self.judge_case(case, [ANSWERS_CLEAN])
        self.assertEqual(self.wait_for_completion(path), [])

    def test_judge_failure_is_unchecked(self):
        case = load_fixture()["fires"][0]
        path = self.judge_case(case, [MISSING])
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_stop_hook_active_returns_without_queueing(self):
        case = load_fixture()["fires"][0]
        path = transcript_for(case, self.hook_state.name)
        self.use_runners(ANSWERS_HIT)
        self.assertEqual(run_claude({
            "last_assistant_message": case["reply"],
            "transcript_path": path,
            "stop_hook_active": True,
        }), "")
        self.assertFalse(os.path.isdir(os.path.join(self.state.name, "jobs")))

    def test_duplicate_reply_is_not_queued_twice(self):
        case = load_fixture()["fires"][0]
        path = transcript_for(case, self.hook_state.name)
        self.use_runners(ANSWERS_HIT)
        payload = {"last_assistant_message": case["reply"], "transcript_path": path}
        self.assertEqual(run_claude(payload), "")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not os.path.isdir(os.path.join(self.state.name, "jobs")):
            time.sleep(0.05)
        self.assertIsNone(detect.enqueue_judge(payload))

    def test_unreadable_transcript_fails_open(self):
        self.use_runners(ANSWERS_HIT)
        self.assertEqual(run_claude({
            "last_assistant_message": load_fixture()["fires"][0]["reply"],
            "transcript_path": os.path.join(self.hook_state.name, "missing.jsonl"),
        }), "")
        self.assertFalse(os.path.isdir(os.path.join(self.state.name, "jobs")))

    def test_stdin_garbage_fails_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
