#!/usr/bin/env python3
"""Unit tests for bug-complaint-leak hooks.

Run: python3 -m unittest discover -s hooks/bug-complaint-leak/tests -v
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

import claude_pretooluse_grep  # noqa: E402
import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402
import state  # noqa: E402


INCIDENT_SLACK = """
We have a bug in Slack planning after LGTM.
Repro: the host says "Draft not shown: the plan doctor rejected it." and
"Nothing was submitted." — it doesn't keep repairing until doctor passes.
"""


class TestDetect(unittest.TestCase):
    def test_incident_slack_paste_fires(self):
        self.assertTrue(detect.is_bug_complaint(INCIDENT_SLACK))
        checklist = detect.build_checklist(INCIDENT_SLACK)
        self.assertIn("git log --all -S", checklist)
        self.assertIn("origin/master", checklist)
        self.assertIn("fails closed", checklist)

    def test_add_comment_does_not_fire(self):
        self.assertFalse(detect.is_bug_complaint("add a comment to Foo.ts"))


class TestPromptSubmit(unittest.TestCase):
    def test_injects_additional_context_on_bug(self):
        out = io.StringIO()
        err = io.StringIO()
        payload = {"prompt": INCIDENT_SLACK, "session_id": "test-bug-1"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(state, "STATE_DIR", tmp):
                with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                    with patch.object(sys, "stdout", out):
                        with redirect_stderr(err):
                            claude_prompt_submit.main()
        data = json.loads(out.getvalue())
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Bug-complaint checklist", ctx)
        self.assertIn("Draft not shown", ctx)

    def test_non_bug_emits_nothing(self):
        out = io.StringIO()
        payload = {"prompt": "add a comment to Foo.ts", "session_id": "test-calm"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(state, "STATE_DIR", tmp):
                with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                    with patch.object(sys, "stdout", out):
                        claude_prompt_submit.main()
        self.assertEqual(out.getvalue().strip(), "")


class TestPreToolUseGrep(unittest.TestCase):
    def test_two_empty_quoted_greps_block(self):
        payload = {"session_id": "grep-1", "tool_name": "Grep", "tool_input": {"pattern": "Draft not shown"}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(state, "STATE_DIR", tmp):
                state.remember_bug_complaint(
                    payload,
                    INCIDENT_SLACK,
                    ["Draft not shown: the plan doctor rejected it."],
                    "checklist",
                )
                state.record_empty_grep(payload, "Draft not shown", "", "")
                state.record_empty_grep(payload, "Draft not shown", "", "")
                err = io.StringIO()
                with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                    with redirect_stderr(err):
                        with self.assertRaises(SystemExit) as cm:
                            claude_pretooluse_grep.main()
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("origin/master", err.getvalue())

    def test_exact_repeat_grep_blocks(self):
        payload = {
            "session_id": "grep-2",
            "tool_name": "Grep",
            "tool_input": {"pattern": "foo", "path": "src", "glob": "*.ts"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(state, "STATE_DIR", tmp):
                st = state.load_state(payload)
                st["last_grep_sig"] = state.grep_signature("foo", "src", "*.ts")
                state.save_state(payload, st)
                err = io.StringIO()
                with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                    with redirect_stderr(err):
                        with self.assertRaises(SystemExit) as cm:
                            claude_pretooluse_grep.main()
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("Exact-repeat Grep", err.getvalue())

    def test_parse_error_fails_open(self):
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            claude_pretooluse_grep.main()  # no raise


if __name__ == "__main__":
    unittest.main()
