#!/usr/bin/env python3
"""Tests for the narrow-the-scope PostToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/narrow-the-scope/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "real_edit_streak_2026-09-01.json")


def load_sequence():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def payload_for(step: dict, session: str) -> dict:
    if step["tool"] == "Bash":
        return {"session_id": session, "tool_name": "Bash", "tool_input": {"command": step["command"]}}
    return {"session_id": session, "tool_name": step["tool"], "tool_input": {"file_path": step["file_path"]}}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CATSTACK_NARROW_THE_SCOPE_STATE_DIR"] = self.tmp.name
        for mod in ("state", "detect", "claude_posttooluse"):
            sys.modules.pop(mod, None)
        import detect  # noqa: F401
        import claude_posttooluse  # noqa: F401
        self.detect = detect
        self.hook = claude_posttooluse

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("CATSTACK_NARROW_THE_SCOPE_STATE_DIR", None)

    def run_hook(self, payload: dict) -> str:
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with redirect_stdout(out):
                self.hook.main()
        return out.getvalue()


class TestFires(_Base):
    def test_fires_on_real_six_edit_streak_at_third_edit(self):
        fx = load_sequence()
        fired_at = []
        for i, step in enumerate(fx["sequence"], 1):
            text = self.detect.observe(payload_for(step, "real"))
            if text:
                fired_at.append(i)
        self.assertEqual(fired_at, [fx["fires_at_step"]], "fires exactly once, at the third edit of the same file")
        self.assertIn(os.path.basename(fx["file"]), self.detect.reminder_text(fx["file"], 3))

    def test_hook_emits_additional_context_json(self):
        p = {"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "/x/a.py"}}
        self.assertEqual(self.run_hook(p), "")
        self.assertEqual(self.run_hook(p), "")
        out = json.loads(self.run_hook(p))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("narrow-the-scope: 3 edits to /x/a.py", out["hookSpecificOutput"]["additionalContext"])

    def test_fires_again_after_a_verify_reset_starts_a_new_streak(self):
        edit = {"session_id": "s2", "tool_name": "Edit", "tool_input": {"file_path": "/x/a.py"}}
        test = {"session_id": "s2", "tool_name": "Bash", "tool_input": {"command": "python3 -m pytest tests -q"}}
        seq = [edit, edit, edit, test, edit, edit, edit]
        fired = [i for i, p in enumerate(seq, 1) if self.detect.observe(p)]
        self.assertEqual(fired, [3, 7])


class TestStaysSilent(_Base):
    def test_silent_when_real_streak_is_interleaved_with_a_test_run(self):
        fx = load_sequence()
        seq = list(fx["sequence"])
        seq.insert(3, {"tool": "Bash", "command": "pnpm test packages/surfaces"})
        seq.insert(6, {"tool": "Bash", "command": "pnpm test packages/surfaces"})
        fired = [i for i, s in enumerate(seq, 1) if self.detect.observe(payload_for(s, "interleaved"))]
        self.assertEqual(fired, [])

    def test_silent_on_edits_to_different_files(self):
        for f in ("/x/a.py", "/x/b.py", "/x/c.py", "/x/d.py"):
            self.assertIsNone(self.detect.observe({"session_id": "s3", "tool_name": "Edit", "tool_input": {"file_path": f}}))

    def test_silent_on_non_verify_bash_and_unrelated_tools(self):
        self.assertIsNone(self.detect.observe({"session_id": "s4", "tool_name": "Bash", "tool_input": {"command": "git status"}}))
        self.assertIsNone(self.detect.observe({"session_id": "s4", "tool_name": "Read", "tool_input": {"file_path": "/x/a.py"}}))

    def test_fails_open_on_garbage_stdin(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stdout(out):
                self.hook.main()
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
