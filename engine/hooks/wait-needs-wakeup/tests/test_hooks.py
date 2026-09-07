#!/usr/bin/env python3
"""Tests for the wait-needs-wakeup hook (PreToolUse on Bash + Stop).

Run: python3 -m unittest discover -s engine/hooks/wait-needs-wakeup/tests -v

Fixtures under tests/fixtures/ are sanitized replays of one real Claude Code
session: the Bash poll loops it ran in the foreground (`until ... sleep 3`,
`for i in $(seq ...) ... sleep 5`, the bare `sleep 90` the harness itself
refused) and the replies it ended turns with ("Nothing needed from you for
about 10 minutes", "A watcher will ... report all three") with no clock-time
ETA and no scheduled wakeup. The *_fires files must block; the *_silent
files (the background/until forms, the corrected replies) must pass.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import backtest  # noqa: E402
import claude_pretooluse  # noqa: E402
import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def run_entry(module, payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                module.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


class TestPreToolUseBlocksRealPolls(unittest.TestCase):
    def test_blocks_each_real_foreground_poll_command(self):
        for case in load("poll_commands_fires.json"):
            with self.subTest(label=case["label"]):
                reason = detect.classify_command(case["command"], case["run_in_background"])
                self.assertIsNotNone(reason, case["command"][:80])

    def test_hook_blocks_with_exit_2_and_wakeup_guidance(self):
        case = load("poll_commands_fires.json")[2]
        code, err = run_entry(claude_pretooluse, {
            "tool_name": "Bash",
            "tool_input": {"command": case["command"], "run_in_background": False},
        })
        self.assertEqual(code, 2)
        self.assertIn("schedule a wakeup", err)
        self.assertIn("wait-needs-wakeup", err)

    def test_blocks_bare_sleep_90_the_harness_refused(self):
        reason = detect.classify_command("sleep 90; gh pr view 228 --json state", False)
        self.assertEqual(reason, "bare foreground sleep of 90s")

    def test_blocks_sleep_in_minutes_unit(self):
        self.assertIsNotNone(detect.classify_command("sleep 2m; gh run list", False))

    def test_blocks_background_loop_that_never_exits(self):
        reason = detect.classify_command("while true; do gh pr view 1 -q .state; sleep 15; done", True)
        self.assertIn("never exits", reason)


class TestPreToolUseAllowsCorrectedForms(unittest.TestCase):
    def test_allows_each_real_or_corrected_silent_command(self):
        for case in load("poll_commands_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.classify_command(case["command"], case["run_in_background"]))

    def test_allows_background_until_loop_via_hook(self):
        code, err = run_entry(claude_pretooluse, {
            "tool_name": "Bash",
            "tool_input": {
                "command": "until gh pr view 228 --json state -q .state | grep -q MERGED; do sleep 30; done",
                "run_in_background": True,
            },
        })
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_allows_monitor_and_schedule_wakeup_tools(self):
        for name in ("Monitor", "ScheduleWakeup"):
            with self.subTest(tool=name):
                self.assertIsNone(detect.decide_pretooluse({
                    "tool_name": name,
                    "tool_input": {"command": "until grep -q '^exit=' out; do sleep 5; done"},
                }))

    def test_allows_short_settle_sleep(self):
        self.assertIsNone(detect.classify_command("gh pr merge 7 --merge; sleep 3; gh pr view 7", False))

    def test_allows_no_sleep_fails_open_on_garbage(self):
        self.assertIsNone(detect.decide_pretooluse({"tool_name": "Bash", "tool_input": {}}))
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_pretooluse.main()
        self.assertEqual(err.getvalue(), "")


class TestStopBlocksRealWaitReplies(unittest.TestCase):
    def test_blocks_each_real_wait_reply_without_eta_or_wakeup(self):
        for case in load("wait_replies_fires.json"):
            with self.subTest(label=case["label"]):
                lines = detect.parse_lines(json.dumps(line) for line in case["transcript"])
                self.assertIsNotNone(detect.decide_stop_from_lines(case["reply"], lines))

    def test_hook_blocks_ten_minute_reply_with_exit_2(self):
        case = load("wait_replies_fires.json")[0]
        path = transcript_file(case["transcript"])
        try:
            code, err = run_entry(claude_stop_check, {
                "last_assistant_message": case["reply"], "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("clock-time ETA", err)
        self.assertIn("schedule the wakeup", err)

    def test_blocks_when_eta_named_but_no_wakeup(self):
        reply = "Nothing needed from you for about 10 minutes; back at 07:26 UTC."
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, []))

    def test_blocks_when_wakeup_scheduled_but_no_eta(self):
        case = load("wait_replies_silent.json")[0]
        lines = detect.parse_lines(json.dumps(line) for line in case["transcript"])
        reply = "Nothing needed from you for about 10 minutes while the agent runs."
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines))

    def test_past_clock_time_is_not_an_eta(self):
        self.assertFalse(detect.has_clock_eta("The watcher reported #228 merged at 07:24 UTC."))
        self.assertTrue(detect.has_clock_eta("I will be back at 07:26 UTC."))
        self.assertTrue(detect.has_clock_eta("Next update by 07:40 UTC."))


class TestStopAllowsCorrectedReplies(unittest.TestCase):
    def test_allows_each_corrected_or_clean_reply(self):
        for case in load("wait_replies_silent.json"):
            with self.subTest(label=case["label"]):
                lines = detect.parse_lines(json.dumps(line) for line in case["transcript"])
                self.assertIsNone(detect.decide_stop_from_lines(case["reply"], lines))

    def test_allows_ten_minute_reply_with_schedule_wakeup_and_eta_via_hook(self):
        case = load("wait_replies_silent.json")[0]
        path = transcript_file(case["transcript"])
        try:
            code, err = run_entry(claude_stop_check, {
                "last_assistant_message": case["reply"], "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_allows_when_stop_hook_active(self):
        case = load("wait_replies_fires.json")[0]
        self.assertIsNone(detect.decide_stop({
            "last_assistant_message": case["reply"], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        case = load("wait_replies_fires.json")[0]
        self.assertIsNone(detect.decide_stop({
            "last_assistant_message": case["reply"], "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


class TestBacktestReproducesTheIncident(unittest.TestCase):
    def test_backtest_counts_fires_fixtures_as_blocked_and_silent_as_zero(self):
        counts = backtest.run_fixtures(FIXTURES)
        self.assertEqual(counts["poll_commands_fires.json"]["blocked"], counts["poll_commands_fires.json"]["total"])
        self.assertEqual(counts["poll_commands_silent.json"]["blocked"], 0)
        self.assertEqual(counts["wait_replies_fires.json"]["blocked"], counts["wait_replies_fires.json"]["total"])
        self.assertEqual(counts["wait_replies_silent.json"]["blocked"], 0)

    def test_backtest_flags_poll_and_wait_reply_in_a_synthetic_transcript(self):
        lines = [
            {"type": "user", "message": {"role": "user", "content": "land it"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "until grep -q '^exit=' out; do sleep 3; done"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "exit=0"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "A watcher will report all three. Nothing needed from you."}]}},
            {"type": "user", "message": {"role": "user", "content": "ok"}},
        ]
        path = transcript_file(lines)
        try:
            report = backtest.run_transcript(path)
        finally:
            os.unlink(path)
        self.assertEqual(report["bash_commands"], 1)
        self.assertEqual(report["poll_blocked"], 1)
        self.assertEqual(report["final_replies"], 1)
        self.assertEqual(report["wait_replies"], 1)
        self.assertEqual(report["reply_blocked"], 1)


if __name__ == "__main__":
    unittest.main()
