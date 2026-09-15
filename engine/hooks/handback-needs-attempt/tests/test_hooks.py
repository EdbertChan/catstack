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
from unittest.mock import Mock, patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)
import claude_stop_check
import detect
import install_claude_hook

JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
sys.path.insert(0, JUDGE_DIR)
import inbox
import judge

FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures", "handbacks.json")
PY = sys.executable
ANSWER_RUNNER = [
    "fake",
    [
        PY,
        "-c",
        "import json,sys; p=sys.argv[-1].lower().split('text:\\n')[-1]; blocked=('permission to use', 'permission prompt is required', 'sandbox refused', 'classifier refused', 'password', 'oauth consent', 'physical device', 'hardware prompt', 'i ran invoker-cli setup slack'); print(json.dumps({'match': not any(x in p for x in blocked), 'closest': ''}))",
        "{prompt}",
    ],
]


def transcript(reply: str, tool_result: str = "") -> str:
    lines = [{"type": "user", "message": {"role": "user", "content": "finish setup"}}]
    if tool_result:
        lines.extend([
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "invoker-cli setup slack"}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": tool_result}]}}
        ])
    lines.append({"type": "assistant", "message": {"role": "assistant", "content": reply}})
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    handle.write("\n".join(json.dumps(line) for line in lines) + "\n")
    handle.close()
    return handle.name


class TestHandbackNeedsAttempt(unittest.TestCase):
    def setUp(self):
        self.judge_state = tempfile.TemporaryDirectory()
        self.hook_state = tempfile.TemporaryDirectory()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)
        self.env = patch.dict(os.environ, {
            judge.STATE_ENV: self.judge_state.name,
            judge.RUNNERS_ENV: json.dumps([ANSWER_RUNNER]),
            "HANDBACK_NEEDS_ATTEMPT_STATE_DIR": self.hook_state.name,
        })
        self.env.start()
        detect.STATE_DIR = self.hook_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 10
        while os.path.isdir(os.path.join(self.judge_state.name, "jobs")) and os.listdir(os.path.join(self.judge_state.name, "jobs")) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.env.stop()
        self.judge_state.cleanup()
        self.hook_state.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def run_case(self, reply: str, tool_result: str = "") -> list[str]:
        path = transcript(reply, tool_result)
        try:
            detect.enqueue_judge({"transcript_path": path, "last_assistant_message": reply})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                messages = inbox.messages(path)
                if messages:
                    return messages
                time.sleep(0.05)
            return inbox.messages(path)
        finally:
            os.unlink(path)

    def test_dictionary_loads(self):
        dictionary = detect._phrases().load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")

    def test_fires_on_command_handback_without_attempt(self):
        with open(FIXTURES, encoding="utf-8") as handle:
            case = json.load(handle)[0]
        messages = self.run_case(case["reply"])
        self.assertEqual(len(messages), 1)
        self.assertIn("handback-needs-attempt", messages[0])

    def test_fires_on_xcode_handback_without_attempt(self):
        messages = self.run_case("Simulator build still passes. Now on your end in Xcode:")
        self.assertEqual(len(messages), 1)
        self.assertIn("Attempt the command or step first", messages[0])

    def test_stays_silent_after_permission_denial(self):
        self.assertEqual(self.run_case("Please run the command yourself.", "Permission to use Bash was denied"), [])

    def test_stays_silent_after_permission_prompt(self):
        self.assertEqual(self.run_case("Please run the command yourself.", "A permission prompt is required before I can run this"), [])

    def test_stays_silent_after_sandbox_refusal(self):
        self.assertEqual(self.run_case("Please open Xcode and approve it.", "The sandbox refused access to the simulator"), [])

    def test_stays_silent_after_classifier_refusal(self):
        self.assertEqual(self.run_case("Please run the command yourself.", "The classifier refused the command"), [])

    def test_stays_silent_for_oauth_consent(self):
        self.assertEqual(self.run_case("Please complete the OAuth consent screen on your end."), [])

    def test_stays_silent_for_human_only_hardware(self):
        self.assertEqual(self.run_case("Connect the physical device and tap Trust; that requires your hardware."), [])

    def test_stays_silent_after_agent_attempt(self):
        self.assertEqual(self.run_case("I ran invoker-cli setup slack and it failed; please inspect the error.", "exit status 1"), [])

    def test_judge_receives_reply_and_turn_exchange(self):
        path = transcript("Please run the command yourself.", "Permission to use Bash was denied")
        try:
            fake_judge = Mock()
            fake_judge.enqueue.return_value = "job-1"
            with patch.object(detect, "_judge", return_value=fake_judge):
                detect.enqueue_judge({"transcript_path": path, "last_assistant_message": "Please run the command yourself."})
            job = fake_judge.enqueue.call_args.args[0]
            self.assertIn("LATEST REPLY", job["prompt"])
            self.assertIn("tool_use", job["prompt"])
            self.assertIn("Permission to use Bash was denied", job["prompt"])
        finally:
            os.unlink(path)

    def test_judge_failure_is_unchecked(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([["missing", ["catstack-no-such-runner", "{prompt}"]]])
        messages = self.run_case("Please run the command yourself.")
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_prompted_state_expires(self):
        path = transcript("Please run the command yourself.")
        try:
            detect.mark_prompted(path)
            self.assertTrue(detect.already_prompted(path))
            with patch.object(detect, "STATE_TTL_SECONDS", 0):
                self.assertFalse(detect.already_prompted(path))
        finally:
            os.unlink(path)

    def test_malformed_prompted_state_is_not_treated_as_prompted(self):
        path = transcript("Please run the command yourself.")
        try:
            state_path = detect._state_file(path)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as handle:
                handle.write("not json")
            self.assertFalse(detect.already_prompted(path))
        finally:
            os.unlink(path)

    def test_stop_hook_is_fail_open_and_returns_early(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps({"stop_hook_active": True, "last_assistant_message": "Please run it"}))):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_unreadable_transcript_fails_open(self):
        self.assertIsNone(detect.enqueue_judge({"transcript_path": "/no/such/transcript", "last_assistant_message": "Please run the command yourself."}))

    def test_malformed_stdin_fails_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_install_merges_stop_idempotently(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 keep.py"}]}]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("handback-needs-attempt/claude_stop_check.py", commands[-1])


if __name__ == "__main__":
    unittest.main()
