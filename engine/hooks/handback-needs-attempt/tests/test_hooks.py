#!/usr/bin/env python3
"""Tests for handback-needs-attempt."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import warnings
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
SLACK_REPLY = "Please run: invoker-cli setup slack ... then tell me when it completes"
XCODE_REPLY = "Simulator build still passes. Now on your end in Xcode:"
OAUTH_REPLY = "Open the link in your browser and approve the OAuth consent screen, then tell me when it is done."
DENIED = "Permission to use Bash with command invoker-cli setup slack has been denied."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": SLACK_REPLY})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def text_row(role: str, text: str) -> dict:
    return {"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}}


def tool_rows(command: str, result: str, is_error: bool = False, tool_id: str = "toolu_1") -> list[dict]:
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": result}]},
         "toolUseResult": {"stdout": result}},
    ]


def run_claude(payload) -> str:
    err = io.StringIO()
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    with patch.object(sys, "stdin", io.StringIO(raw)), redirect_stderr(err):
        claude_stop_check.main()
    return err.getvalue()


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.hook_state = tempfile.TemporaryDirectory()
        self.old_state_dir = detect.STATE_DIR
        detect.STATE_DIR = self.hook_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        self.use_runners(ANSWERS_HIT)
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        detect.STATE_DIR = self.old_state_dir
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        self.hook_state.cleanup()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, *rows: dict, name: str = "session.jsonl") -> str:
        path = os.path.join(self.hook_state.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def queued_prompt(self) -> str:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for name in self.jobs():
                try:
                    with open(os.path.join(self.state.name, "jobs", name), encoding="utf-8") as handle:
                        return json.load(handle)["prompt"]
                except (OSError, ValueError):
                    time.sleep(0.05)
            time.sleep(0.05)
        self.fail("no judge job was queued")

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            got = judge_inbox.messages(path)
            if got:
                return got
            time.sleep(0.1)
        return []

    def wait_until_drained(self) -> None:
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)

    def test_dictionary_loads_as_exchange_checker(self):
        dictionary = phrases.load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")
        self.assertEqual(dictionary["reads"], "exchange")
        self.assertIn(SLACK_REPLY, dictionary["match"])
        self.assertIn(XCODE_REPLY, dictionary["match"])

    def test_flags_command_handback_without_attempt(self):
        path = self.write_transcript(text_row("user", "set up slack for me"), text_row("assistant", SLACK_REPLY))
        self.assertEqual(run_claude({"transcript_path": path}), "")
        prompt = self.queued_prompt()
        self.assertIn("(no tool calls this turn)", prompt)
        self.assertIn(SLACK_REPLY, prompt)
        on_hit = phrases.load("handback-needs-attempt")["on_hit"]
        self.assertEqual(self.wait_for_messages(path), [on_hit])

    def test_flags_xcode_handback_without_attempt(self):
        path = self.write_transcript(
            text_row("user", "get the ios build running"),
            *tool_rows("xcodebuild -sdk iphonesimulator build", "BUILD SUCCEEDED"),
            text_row("assistant", XCODE_REPLY),
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        prompt = self.queued_prompt()
        self.assertIn("xcodebuild -sdk iphonesimulator build", prompt)
        self.assertIn(XCODE_REPLY, prompt)
        self.assertEqual(len(self.wait_for_messages(path)), 1)

    def test_silent_after_permission_denial(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(
            text_row("user", "set up slack for me"),
            *tool_rows("invoker-cli setup slack", DENIED, is_error=True),
            text_row("assistant", SLACK_REPLY),
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        prompt = self.queued_prompt()
        self.assertIn(f"RESULT (error): {DENIED}", prompt)
        self.assertLess(prompt.index(DENIED), prompt.index("ASSISTANT REPLY:"))
        self.wait_until_drained()
        self.assertEqual(judge_inbox.messages(path), [])

    def test_silent_for_oauth_consent(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(text_row("user", "connect my google drive"), text_row("assistant", OAUTH_REPLY))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertIn(OAUTH_REPLY, self.queued_prompt())
        self.wait_until_drained()
        self.assertEqual(judge_inbox.messages(path), [])

    def test_judge_failure_is_unchecked(self):
        self.use_runners(MISSING)
        path = self.write_transcript(text_row("user", "set up slack"), text_row("assistant", SLACK_REPLY))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_earlier_turn_tools_are_not_in_this_turns_exchange(self):
        rows = [
            text_row("user", "first ask"),
            *tool_rows("invoker-cli setup slack", "done", tool_id="toolu_old"),
            text_row("assistant", "Done."),
            text_row("user", "now the second ask"),
            *tool_rows("ls", "README.md", tool_id="toolu_new"),
        ]
        exchange = detect.tool_exchange(rows)
        self.assertEqual(len(exchange), 2)
        self.assertTrue(exchange[0].startswith("CALL Bash:"))
        self.assertIn("ls", exchange[0])
        self.assertNotIn("invoker-cli", "\n".join(exchange))

    def test_tool_result_and_meta_rows_do_not_move_the_turn_start(self):
        meta = dict(text_row("user", "Stop hook feedback: something"), isMeta=True)
        rows = [
            text_row("user", "set up slack"),
            *tool_rows("invoker-cli setup slack", DENIED, is_error=True),
            meta,
        ]
        exchange = detect.tool_exchange(rows)
        self.assertEqual(exchange[1], f"RESULT (error): {DENIED}")

    def test_duplicate_reply_and_exchange_is_not_queued_twice(self):
        path = self.write_transcript(text_row("user", "set up slack"), text_row("assistant", SLACK_REPLY))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))

    def test_same_reply_after_an_attempt_fires_again(self):
        path = self.write_transcript(text_row("user", "set up slack"), text_row("assistant", SLACK_REPLY))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.wait_until_drained()
        self.write_transcript(
            text_row("user", "set up slack"),
            *tool_rows("invoker-cli setup slack", DENIED, is_error=True),
            text_row("assistant", SLACK_REPLY),
        )
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))

    def test_not_queued_when_stop_hook_active(self):
        path = self.write_transcript(text_row("user", "set up slack"), text_row("assistant", SLACK_REPLY))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "stop_hook_active": True}))
        self.assertEqual(self.jobs(), [])

    def test_empty_reply_is_not_queued(self):
        path = self.write_transcript(text_row("user", "hi"))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_missing_transcript_reports_unchecked(self):
        missing = os.path.join(self.hook_state.name, "does-not-exist.jsonl")
        err = run_claude({"transcript_path": missing, "last_assistant_message": SLACK_REPLY})
        self.assertIn("handback-needs-attempt: unchecked, letting this reply through:", err)
        self.assertIn("could not be found", err)
        self.assertEqual(self.jobs(), [])

    def test_no_transcript_reports_unchecked(self):
        err = run_claude({"last_assistant_message": SLACK_REPLY})
        self.assertEqual(
            err,
            "handback-needs-attempt: unchecked, letting this reply through: "
            "the payload names no readable transcript\n",
        )
        self.assertEqual(self.jobs(), [])

    def test_unreadable_transcript_reports_unchecked(self):
        path = self.write_transcript(text_row("user", "set up slack"), text_row("assistant", SLACK_REPLY))
        with patch("builtins.open", side_effect=PermissionError("denied")):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertIn("handback-needs-attempt: unchecked, letting this reply through:", err.getvalue())
        self.assertIn("could not be read", err.getvalue())
        self.assertEqual(self.jobs(), [])

    def test_malformed_stdin_fails_open(self):
        self.assertEqual(run_claude("not-json"), "")
        self.assertEqual(self.jobs(), [])

    def test_enqueue_error_fails_open_with_hook_error(self):
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("boom")):
            err = run_claude({"last_assistant_message": SLACK_REPLY})
        self.assertEqual(err, "catstack-hook-error handback-needs-attempt: RuntimeError: boom\n")

    def test_install_merges_stop_idempotently(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "other"}]}]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(commands.count("other"), 1)
        self.assertEqual(sum(install_claude_hook.MARKER in c for c in commands), 1)
