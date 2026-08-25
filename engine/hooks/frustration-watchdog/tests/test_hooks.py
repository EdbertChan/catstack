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


if __name__ == "__main__":
    unittest.main()
