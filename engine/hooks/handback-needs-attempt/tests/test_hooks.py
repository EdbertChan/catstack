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
sys.path.insert(0, HOOK_DIR)

import claude_stop_check
import detect

sys.path.append(os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))
sys.path.append(os.path.join(os.path.dirname(HOOK_DIR), "_flags"))
import inbox as judge_inbox
from judge_test_base import JudgeTestCase


PY = sys.executable
HANDOFF_RUN = "Please run: invoker-cli setup slack ... then tell me when it completes"
XCODE_HANDOFF = "Simulator build still passes. Now on your end in Xcode:"
PERMISSION_HANDOFF = "Please run invoker-cli setup slack on your end after the permission prompt."
OAUTH_HANDOFF = "Open the browser and finish the OAuth consent on your end."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": HANDOFF_RUN})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            claude_stop_check.main()
    return err.getvalue()


def human_line(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_call(command: str, name: str = "Bash", tool_id: str = "tool-1") -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": tool_id,
                "name": name,
                "input": {"command": command},
            }],
        },
    }


def tool_result(text: str, tool_id: str = "tool-1", **fields) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": text,
            }],
        },
        **fields,
    }


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "HOME": self.work.name,
            "CATSTACK_REFLECT_ENFORCEMENT": "1",
        })
        self.env.start()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.env.stop()
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self):
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def transcript(self, *rows) -> str:
        path = os.path.join(self.work.name, "session.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def payload(self, reply: str, path: str) -> dict:
        return {
            "last_assistant_message": reply,
            "transcript_path": path,
            "cwd": self.work.name,
        }

    def wait_for_messages(self, path: str) -> list[str]:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            messages = judge_inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.1)
        return []

    def test_flags_invoker_setup_without_attempt(self):
        self.use_runners(ANSWERS_HIT)
        path = self.transcript(human_line("set up Slack"))
        job_id = detect.enqueue_judge(self.payload(HANDOFF_RUN, path), "claude")
        self.assertIsNotNone(job_id)
        messages = self.wait_for_messages(path)
        self.assertTrue(any("handback-needs-attempt" in message for message in messages))

    def test_flags_xcode_handback_without_attempt(self):
        self.use_runners(ANSWERS_HIT)
        path = self.transcript(human_line("build the simulator"))
        self.assertIsNotNone(detect.enqueue_judge(self.payload(XCODE_HANDOFF, path), "claude"))
        messages = self.wait_for_messages(path)
        self.assertTrue(any("handback-needs-attempt" in message for message in messages))

    def test_silent_after_permission_denial(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.transcript(
            human_line("set up Slack"),
            tool_call("invoker-cli setup slack"),
            tool_result("Permission denied by the sandbox classifier.", is_error=True, toolDenialKind="sandbox"),
        )
        self.assertIsNotNone(detect.enqueue_judge(self.payload(PERMISSION_HANDOFF, path), "claude"))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_silent_on_oauth_consent_handback(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.transcript(
            human_line("connect the Slack account"),
            tool_call("open https://slack.example/oauth", name="Bash"),
            tool_result("The browser is waiting for OAuth consent; only the user can approve it.", is_error=True),
        )
        self.assertIsNotNone(detect.enqueue_judge(self.payload(OAUTH_HANDOFF, path), "claude"))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_judge_failure_is_unchecked_not_clean(self):
        self.use_runners(MISSING)
        path = self.transcript(human_line("set up Slack"))
        self.assertIsNotNone(detect.enqueue_judge(self.payload(HANDOFF_RUN, path), "claude"))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])
        self.assertNotIn("handback-needs-attempt: this reply hands", messages[0])

    def test_unreadable_transcript_is_reported_unchecked(self):
        err = io.StringIO()
        with patch.object(sys, "stderr", err):
            result = detect.enqueue_judge(self.payload(HANDOFF_RUN, "/missing/session.jsonl"), "claude")
        self.assertIsNone(result)
        self.assertIn("catstack-hook-unchecked handback-needs-attempt", err.getvalue())

    def test_stop_hook_active_stays_silent(self):
        path = self.transcript(human_line("set up Slack"))
        self.assertIsNone(detect.enqueue_judge({**self.payload(HANDOFF_RUN, path), "stop_hook_active": True}, "claude"))
        self.assertEqual(self.jobs(), [])

    def test_stop_wrapper_never_blocks_the_reply(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.transcript(human_line("set up Slack"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            self.assertEqual(run_claude(self.payload(HANDOFF_RUN, path)), "")

    def test_job_contains_turn_tool_calls_and_results(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.transcript(
            human_line("set up Slack"),
            tool_call("invoker-cli setup slack"),
            tool_result("classifier refused the command", is_error=True),
        )
        self.assertIsNotNone(detect.enqueue_judge(self.payload(PERMISSION_HANDOFF, path), "claude"))
        deadline = time.monotonic() + 5
        while not self.jobs() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.jobs())
        with open(os.path.join(self.state.name, "jobs", self.jobs()[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn("invoker-cli setup slack", job["prompt"])
        self.assertIn("classifier refused the command", job["prompt"])
        self.assertIn(PERMISSION_HANDOFF, job["prompt"])


if __name__ == "__main__":
    unittest.main()
