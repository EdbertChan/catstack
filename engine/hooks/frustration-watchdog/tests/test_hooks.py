#!/usr/bin/env python3
"""Unit tests for the user-waiting watchdog Stop hook.

Run: python3 -m unittest discover -s hooks/frustration-watchdog/tests -v

Fixture texts replicate the 2026-08-17 live-demo session that motivated the
hook ("i am waiting for you to do something" after a turn of invisible
background work) — the backtest cases are those real message shapes.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402


def transcript_with(user_texts):
    """user_texts: [(iso_ts, text)] -> temp claude-format JSONL path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for ts, text in user_texts:
        d = {"type": "user", "message": {"role": "user", "content": text}}
        if ts:
            d["timestamp"] = ts
        f.write(json.dumps(d) + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {}, "content": []}}) + "\n")
    f.close()
    return f.name


def run_hook(transcript_path, assistant_message, stop_hook_active=False):
    """Returns (blocked, stderr_text)."""
    payload = {
        "transcript_path": transcript_path,
        "last_assistant_message": assistant_message,
        "stop_hook_active": stop_hook_active,
    }
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as e:
                return e.code == 2, err.getvalue()
    return False, err.getvalue()


class TestWatchdog(unittest.TestCase):
    def test_waiting_user_with_no_next_step_blocks(self):
        # Real shape from the motivating session: user says they're waiting,
        # assistant reply only narrates background work.
        path = transcript_with([("2026-08-18T02:13:30Z", "i am waiting for you to do something")])
        try:
            blocked, err = run_hook(path, "I'm cancelling the stale captures and preparing the environment for the next phase.")
            self.assertTrue(blocked)
            self.assertIn("impatience-shaped", err)
        finally:
            os.unlink(path)

    def test_waiting_user_with_concrete_action_passes(self):
        path = transcript_with([("2026-08-18T02:13:30Z", "i am waiting for you to do something")])
        try:
            blocked, _ = run_hook(path, "New tab is starting now — close the two old NiceSpeak tabs, stay on the new one, and TALK.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_direct_question_counts_as_handoff(self):
        path = transcript_with([("2026-08-18T02:13:30Z", "WHY ARE WE NOT LAUNCHING A ZOOM MEETING RIGHT NOW")])
        try:
            blocked, _ = run_hook(path, "Zoom is launching. Do you want the phone as the second participant?")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_eta_counts_as_handoff(self):
        path = transcript_with([("2026-08-18T02:13:30Z", "i am waiting for you to do something")])
        try:
            blocked, _ = run_hook(path, "The face is still baking; nothing needed from you for ~2 min.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_calm_user_never_blocks(self):
        path = transcript_with([("2026-08-18T02:13:30Z", "sounds good, take your time")])
        try:
            blocked, _ = run_hook(path, "Continuing with the migration in the background.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_verbatim_repeat_within_window_blocks(self):
        path = transcript_with([
            ("2026-08-18T02:30:00Z", "where is my digital twin? when can i speak and test"),
            ("2026-08-18T02:33:00Z", "where is my digital twin? when can i speak and test"),
        ])
        try:
            blocked, err = run_hook(path, "Still working through the avatar configuration internals.")
            self.assertTrue(blocked)
            self.assertIn("verbatim-repeat", err)
        finally:
            os.unlink(path)

    def test_repeat_outside_window_is_calm(self):
        path = transcript_with([
            ("2026-08-18T02:00:00Z", "where is my digital twin? when can i speak and test"),
            ("2026-08-18T02:20:00Z", "where is my digital twin? when can i speak and test"),
        ])
        try:
            blocked, _ = run_hook(path, "Still working through the avatar configuration internals.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_stop_hook_active_never_blocks(self):
        path = transcript_with([("2026-08-18T02:13:30Z", "i am waiting for you to do something")])
        try:
            blocked, _ = run_hook(path, "Narrating with no action.", stop_hook_active=True)
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_injected_and_tool_result_lines_are_ignored(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "all good, thanks"}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "I AM WAITING ??? WHAT THE FUCK"}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content":
            "<task-notification>i am waiting for you to do something</task-notification>"}}) + "\n")
        f.close()
        try:
            blocked, _ = run_hook(f.name, "Narrating with no action.")
            self.assertFalse(blocked)
        finally:
            os.unlink(f.name)

    def test_hook_feedback_lines_do_not_hide_the_users_verbatim_repeat(self):
        path = transcript_with([
            ("2026-08-18T02:30:00Z", "where is my digital twin? when can i speak and test"),
            ("2026-08-18T02:31:00Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 200 words"),
            ("2026-08-18T02:31:10Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 180 words"),
            ("2026-08-18T02:31:20Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 170 words"),
            ("2026-08-18T02:31:30Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 160 words"),
            ("2026-08-18T02:31:40Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 155 words"),
            ("2026-08-18T02:31:50Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 152 words"),
            ("2026-08-18T02:32:00Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 151 words"),
            ("2026-08-18T02:32:10Z", "Stop hook feedback: [python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 151 words"),
            ("2026-08-18T02:33:00Z", "where is my digital twin? when can i speak and test"),
        ])
        try:
            blocked, err = run_hook(path, "Still working through the avatar configuration internals.")
            self.assertTrue(blocked)
            self.assertIn("verbatim-repeat", err)
        finally:
            os.unlink(path)

    def test_hook_feedback_as_last_line_is_not_the_user_and_stays_calm(self):
        path = transcript_with([
            ("2026-08-18T02:30:00Z", "sounds good, take your time"),
            ("2026-08-18T02:31:00Z", "Stop hook feedback: [frustration-watchdog]: The user's last message was impatience-shaped ??? you messed up"),
        ])
        try:
            blocked, _ = run_hook(path, "Continuing with the migration in the background.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_missing_transcript_fails_open(self):
        blocked, _ = run_hook("/nonexistent/transcript.jsonl", "Narrating with no action.")
        self.assertFalse(blocked)

    def test_agent_blame_blocks_product_blame_does_not(self):
        path = transcript_with([("2026-08-24T01:00:00Z", "you messed up the merge")])
        try:
            blocked, err = run_hook(path, "Continuing with the migration in the background.")
            self.assertTrue(blocked)
            self.assertIn("agent-blame", err)
        finally:
            os.unlink(path)

        path = transcript_with([("2026-08-24T01:00:00Z", "ok so the ui is just messed up then")])
        try:
            blocked, _ = run_hook(path, "Continuing with the migration in the background.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)


DEFAULT_WAITING_FEEDBACK = (
    "The user's last message was impatience-shaped (waiting) and this reply hands "
    "them nothing visible. End the wait: give exactly one concrete action for the "
    "user (\"click X\", \"run Y\", \"say Z\"), ask them a direct question, or state an "
    "explicit no-action window (\"nothing needed from you for ~2 min\"). Per "
    "CLAUDE.md live-demo rules.\n"
)
"""Today's block text for a "waiting" message, captured from the hook before the
refusal branch existed. A turn with no hook refusal must still get exactly this."""
HOOK_REFUSAL_TEXT = (
    "PreToolUse:Bash hook error: [python3 $HOME/.claude/hooks/pr-schema-gate/"
    "claude_pretooluse.py]: Direct 'gh pr create' bypasses the make-pr/draft-pr PR-body schema"
)
"""Real shape of a PreToolUse refusal as Claude Code writes it to the transcript."""
WAITING = "i am waiting for you to do something"
NARRATION = "The PR step is stuck behind a guard; looking into it."


def tool_turn(result_text, is_error=True):
    """An assistant tool call followed by its tool_result line."""
    return [
        {"type": "assistant", "message": {"id": "m1", "usage": {}, "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "gh pr create"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": is_error, "content": result_text}]}},
    ]


def transcript_lines(lines):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for d in lines:
        f.write(json.dumps(d) + "\n")
    f.close()
    return f.name


def human(text, ts="2026-08-18T02:13:30Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


class TestWordingAfterHookRefusal(unittest.TestCase):
    """When a hook refused a tool call this turn, the block asks for a question
    or a no-action window, not a user action: the assistant is the one blocked."""

    def run_lines(self, lines, reply=NARRATION):
        path = transcript_lines(lines)
        try:
            return run_hook(path, reply)
        finally:
            os.unlink(path)

    def test_hook_refusal_in_turn_blocks_with_question_or_window_wording(self):
        blocked, err = self.run_lines([human(WAITING)] + tool_turn(HOOK_REFUSAL_TEXT))
        self.assertTrue(blocked)
        self.assertIn("impatience-shaped (waiting)", err)
        self.assertIn("A hook refused a tool call this turn", err)
        self.assertIn("ask them a direct question, or state an explicit no-action window", err)
        self.assertNotIn("concrete action", err)

    def test_refusal_as_content_blocks_list_is_detected(self):
        lines = [human(WAITING)] + tool_turn([{"type": "text", "text": HOOK_REFUSAL_TEXT}])
        blocked, err = self.run_lines(lines)
        self.assertTrue(blocked)
        self.assertIn("A hook refused a tool call this turn", err)

    def test_same_turn_without_refusal_keeps_todays_bytes(self):
        blocked, err = self.run_lines([human(WAITING)] + tool_turn("Created PR #12", is_error=False))
        self.assertTrue(blocked)
        self.assertEqual(err, DEFAULT_WAITING_FEEDBACK)

    def test_turn_with_no_tool_calls_keeps_todays_bytes(self):
        blocked, err = self.run_lines([human(WAITING)])
        self.assertTrue(blocked)
        self.assertEqual(err, DEFAULT_WAITING_FEEDBACK)

    def test_plain_command_failure_is_not_a_refusal(self):
        lines = [human(WAITING)] + tool_turn("Exit code 1\nfatal: not a git repository")
        blocked, err = self.run_lines(lines)
        self.assertTrue(blocked)
        self.assertEqual(err, DEFAULT_WAITING_FEEDBACK)

    def test_refusal_in_an_earlier_turn_does_not_change_wording(self):
        lines = (
            [human("please open the PR", ts="2026-08-18T02:10:00Z")]
            + tool_turn(HOOK_REFUSAL_TEXT)
            + [human(WAITING)]
        )
        blocked, err = self.run_lines(lines)
        self.assertTrue(blocked)
        self.assertEqual(err, DEFAULT_WAITING_FEEDBACK)

    def test_stop_hook_feedback_does_not_end_the_refusal_turn(self):
        lines = (
            [human(WAITING)]
            + tool_turn(HOOK_REFUSAL_TEXT)
            + [human("Stop hook feedback: [diu-stop]: Apply diu: 200 words", ts="2026-08-18T02:14:00Z")]
        )
        blocked, err = self.run_lines(lines)
        self.assertTrue(blocked)
        self.assertIn("A hook refused a tool call this turn", err)

    def test_refusal_turn_with_a_handoff_still_passes(self):
        """Only the wording changes; whether the hook blocks does not."""
        lines = [human(WAITING)] + tool_turn(HOOK_REFUSAL_TEXT)
        for reply in (
            "A guard blocked the PR. Should I file it through the invoker skill instead?",
            "A guard blocked the PR; nothing needed from you for ~2 min while I reroute it.",
            "A guard blocked the PR — run the make-pr skill when you are back.",
        ):
            blocked, err = self.run_lines(lines, reply=reply)
            self.assertFalse(blocked, reply)
            self.assertEqual(err, "")

    def test_calm_user_with_refusal_never_blocks(self):
        blocked, err = self.run_lines([human("sounds good, take your time")] + tool_turn(HOOK_REFUSAL_TEXT))
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_unreadable_tool_results_use_default_wording_and_say_so(self):
        """Third outcome: the refusal check could not run. The block still
        fires with today's wording, plus a line naming the unchecked read."""
        with patch.object(claude_stop_check, "turn_has_hook_refusal", side_effect=OSError("disk gone")):
            blocked, err = self.run_lines([human(WAITING)] + tool_turn(HOOK_REFUSAL_TEXT))
        self.assertTrue(blocked)
        self.assertTrue(err.startswith(DEFAULT_WAITING_FEEDBACK))
        self.assertIn("could not read this turn's tool results (OSError: disk gone)", err)


if __name__ == "__main__":
    unittest.main()


class TestSubagentStopOptOut(unittest.TestCase):
    """The manifest opts out of SubagentStop with a reason, and the script
    itself returns before reading anything when the payload carries
    `agent_id`: a subagent's user turn is the parent's prompt, which often
    quotes the human verbatim."""

    def test_manifest_opts_out_with_a_reason(self):
        with open(os.path.join(HOOKS_DIR, "claude.hook.json")) as handle:
            manifest = json.load(handle)
        self.assertIs(manifest["subagent_stop"]["inherit"], False)
        self.assertTrue(manifest["subagent_stop"]["reason"].strip())

    def test_subagent_payload_never_blocks_on_quoted_frustration(self):
        quoted = "USER'S DIRECTION (verbatim): \"you fucked up, i am waiting for you to do something\""
        path = transcript_with([("2026-08-18T02:13:30Z", quoted)])
        reply = "Investigating the stalled launch; no visible step yet."
        try:
            blocked_as_main, _ = run_hook(path, reply)
            self.assertTrue(blocked_as_main)
            payload = {
                "transcript_path": path,
                "agent_transcript_path": path,
                "agent_id": "a0231adb57400d820",
                "agent_type": "general-purpose",
                "hook_event_name": "SubagentStop",
                "last_assistant_message": reply,
                "stop_hook_active": False,
            }
            err = io.StringIO()
            with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with redirect_stderr(err):
                    try:
                        claude_stop_check.main()
                    except SystemExit as e:
                        self.fail(f"blocked a subagent with exit {e.code}: {err.getvalue()}")
            self.assertEqual(err.getvalue(), "")
        finally:
            os.unlink(path)
