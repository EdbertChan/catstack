#!/usr/bin/env python3
"""Tests for restart-risk-check.

Run: python3 -m unittest discover -s hooks/restart-risk-check/tests -v
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

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_restart_check  # noqa: E402
import detect  # noqa: E402


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_restart_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def write_transcript(lines: list[dict]) -> str:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for line in lines:
        handle.write(json.dumps(line) + "\n")
    handle.close()
    return handle.name


def user_line(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def bash_call_line(command: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}],
        },
    }


class TestClaimDetection(unittest.TestCase):
    def test_no_hit_without_remote_host_language(self):
        self.assertFalse(detect.claims_restart_is_safe(
            "Restarting the local dev server is safe, low risk."
        ))

    def test_no_hit_without_restart_word(self):
        self.assertFalse(detect.claims_restart_is_safe(
            "This SSH droplet is healthy and safe to use."
        ))

    def test_hit_on_remote_restart_safety_claim(self):
        self.assertTrue(detect.claims_restart_is_safe(
            "No workflows are running there right now, so restart risk is low on this droplet."
        ))

    def test_hit_on_ssh_and_safe_to_restart(self):
        self.assertTrue(detect.claims_restart_is_safe(
            "It's safe to restart the SSH remote target."
        ))

    def test_no_hit_when_restart_and_safety_far_apart(self):
        far = "restart" + (" filler" * 60) + " this remote host is safe for other reasons"
        self.assertFalse(detect.claims_restart_is_safe(far))


class TestDecide(unittest.TestCase):
    def test_no_hit_message_passes_through(self):
        self.assertIsNone(detect.decide({"last_assistant_message": "All tests pass."}))

    def test_stop_hook_active_always_passes(self):
        self.assertIsNone(detect.decide({
            "stop_hook_active": True,
            "last_assistant_message": "Restart risk is low on this droplet.",
        }))

    def test_blocks_with_zero_checks(self):
        path = write_transcript([
            user_line("go check on the droplet"),
            bash_call_line("ls -la"),
        ])
        try:
            result = detect.decide({
                "last_assistant_message": "Restart risk is low on this SSH droplet.",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertIsNotNone(result)
        self.assertIn("workflow/task queue", result)
        self.assertIn("who", result)

    def test_blocks_with_only_queue_check(self):
        path = write_transcript([
            user_line("go check on the droplet"),
            bash_call_line("./run.sh --headless query workflows --output json"),
        ])
        try:
            result = detect.decide({
                "last_assistant_message": "Restart risk is low on this SSH droplet.",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertIsNotNone(result)
        self.assertIn("who", result)
        self.assertNotIn("workflow/task queue", result)

    def test_passes_with_both_checks(self):
        path = write_transcript([
            user_line("go check on the droplet"),
            bash_call_line("./run.sh --headless query workflows --output json"),
            bash_call_line("ssh droplet 'who'"),
        ])
        try:
            result = detect.decide({
                "last_assistant_message": "Restart risk is low on this SSH droplet.",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertIsNone(result)

    def test_only_scans_current_turn(self):
        # Both checks happened in a PRIOR turn; the current turn (after the
        # second user line) has neither, so it should still block.
        path = write_transcript([
            user_line("first ask"),
            bash_call_line("./run.sh --headless query workflows --output json"),
            bash_call_line("ssh droplet 'who'"),
            user_line("second ask, unrelated"),
            bash_call_line("ls -la"),
        ])
        try:
            result = detect.decide({
                "last_assistant_message": "Restart risk is low on this SSH droplet.",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertIsNotNone(result)


class TestClaudeEntrypoint(unittest.TestCase):
    def test_exits_2_on_block(self):
        path = write_transcript([
            user_line("go check on the droplet"),
            bash_call_line("ls -la"),
        ])
        try:
            blocked, err = run_claude({
                "last_assistant_message": "Restart risk is low on this SSH droplet.",
                "transcript_path": path,
            })
        finally:
            os.unlink(path)
        self.assertTrue(blocked)
        self.assertIn("restart", err.lower())

    def test_silent_on_unrelated_message(self):
        blocked, err = run_claude({"last_assistant_message": "The tests pass."})
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_fails_open_on_bad_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_restart_check.main()  # must not raise
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
