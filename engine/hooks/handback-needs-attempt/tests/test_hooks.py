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
sys.path.insert(0, HOOK_DIR)
sys.path.append(os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))

import detect
import inbox
import install_claude_hook
import phrases
from judge_test_base import JudgeTestCase

PY = sys.executable
COMMAND_HAND_BACK = "Please run: invoker-cli setup slack ... then tell me when it completes"
XCODE_HAND_BACK = "Simulator build still passes. Now on your end in Xcode:"
ATTEMPTED_HAND_BACK = "I tried the setup command, but you need to finish the remaining step."
DENIED_HAND_BACK = "Please run the setup command after permission is granted."
OAUTH_HAND_BACK = "Please complete the OAuth consent in your browser, then tell me when it completes."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": COMMAND_HAND_BACK})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def text_line(role: str, text: str) -> str:
    return json.dumps({
        "type": role,
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
    })


def tool_use(name: str, tool_id: str, command: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": tool_id, "name": name,
            "input": {"command": command},
        }]},
    })


def tool_result(tool_id: str, content: str, is_error: bool = False) -> str:
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": tool_id,
            "content": content, "is_error": is_error,
        }]},
        "toolUseResult": {"stdout": content, "is_error": is_error},
    })


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.use_runners(ANSWERS_HIT)
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

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            messages = inbox.messages(path)
            if messages:
                return messages
            if not self.jobs():
                return messages
            time.sleep(0.1)
        return inbox.messages(path)

    def test_dictionary_loads(self):
        dictionary = phrases.load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")
        self.assertIn("attempt", dictionary["on_hit"])

    def test_installer_merge_is_idempotent(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"command": "other"}]}]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        commands = [
            hook["command"]
            for entry in settings["hooks"]["Stop"]
            for hook in entry["hooks"]
        ]
        self.assertEqual(sum("handback-needs-attempt/claude_stop_check.py" in command for command in commands), 1)

    def test_command_handback_without_attempt_flags(self):
        path = self.write_transcript(text_line("user", "set up Slack"))
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": COMMAND_HAND_BACK,
        }))
        self.assertEqual(self.wait_for_messages(path), [phrases.load("handback-needs-attempt")["on_hit"]])

    def test_xcode_handback_without_attempt_flags(self):
        path = self.write_transcript(text_line("user", "build the simulator"))
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": XCODE_HAND_BACK,
        }))
        self.assertEqual(self.wait_for_messages(path), [phrases.load("handback-needs-attempt")["on_hit"]])

    def test_attempted_step_is_silent(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(
            text_line("user", "set up Slack"),
            tool_use("Bash", "tool-1", "invoker-cli setup slack"),
            tool_result("tool-1", "setup could not finish"),
        )
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": ATTEMPTED_HAND_BACK,
        }))
        self.assertEqual(self.wait_for_messages(path), [])

    def test_permission_denial_handback_is_silent(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(
            text_line("user", "set up Slack"),
            tool_use("Bash", "tool-1", "invoker-cli setup slack"),
            tool_result("tool-1", "Permission to use Bash has been denied by your rule", True),
        )
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": DENIED_HAND_BACK,
        }))
        self.assertEqual(self.wait_for_messages(path), [])

    def test_oauth_consent_handback_is_silent(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(text_line("user", "connect the Slack workspace"))
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": OAUTH_HAND_BACK,
        }))
        self.assertEqual(self.wait_for_messages(path), [])

    def test_job_contains_turn_tool_calls_and_results(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(
            text_line("user", "set up Slack"),
            tool_use("Bash", "tool-1", "invoker-cli setup slack"),
            tool_result("tool-1", "setup could not finish"),
        )
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": ATTEMPTED_HAND_BACK,
        }))
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn("invoker-cli setup slack", job["prompt"])
        self.assertIn("setup could not finish", job["prompt"])

    def test_unchecked_judge_is_reported(self):
        self.use_runners(MISSING)
        path = self.write_transcript(text_line("user", "set up Slack"))
        self.assertIsNotNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": COMMAND_HAND_BACK,
        }))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_stop_hook_active_queues_nothing(self):
        path = self.write_transcript(text_line("user", "set up Slack"))
        self.assertIsNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": COMMAND_HAND_BACK,
            "stop_hook_active": True,
        }))
        self.assertEqual(self.jobs(), [])

    def test_unreadable_transcript_is_unchecked(self):
        error = io.StringIO()
        with redirect_stderr(error):
            detect.try_enqueue_judge({
                "transcript_path": os.path.join(self.work.name, "missing.jsonl"),
                "last_assistant_message": COMMAND_HAND_BACK,
            })
        self.assertIn("unchecked", error.getvalue())


if __name__ == "__main__":
    unittest.main()
