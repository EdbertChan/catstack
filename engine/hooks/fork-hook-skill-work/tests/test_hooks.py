#!/usr/bin/env python3
"""Tests for the fork-hook-skill-work PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/fork-hook-skill-work/tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402

UNMANAGED = {}
MANAGED = {"CHIRP_SESSION_ID": "s1", "CHIRP_PROJECT_ID": "p1"}


def edit(path: str, tool: str = "Edit", session: str = "sess-1") -> dict:
    return {"session_id": session, "tool_name": tool, "tool_input": {"file_path": path}}


class ForkNudgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")

    def run_detect(self, event: dict, env: dict) -> list:
        full = {**env, detect.STATE_DIR_ENV: self.state}
        with patch.dict(os.environ, full, clear=True):
            return detect.detect(event)

    def test_fires_on_hook_edit_outside_managed_session(self) -> None:
        findings = self.run_detect(edit("/r/engine/hooks/diu-stop/detect.py"), UNMANAGED)
        self.assertEqual([f.rule_id for f in findings], [detect.RULE_NOT_FORKED])
        self.assertIn("xirp session new", findings[0].message)

    def test_fires_on_every_watched_root(self) -> None:
        for path in (
            *(f"/r/{root}/skills/x/SKILL.md" for root in ("engine", "corpus", "product")),
            "/Users/u/.claude/hooks/_runner/run.py",
            "/Users/u/.claude/skills/diu/SKILL.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(len(self.run_detect(edit(path, session=path), UNMANAGED)), 1)

    def test_silent_inside_managed_session(self) -> None:
        self.assertEqual(self.run_detect(edit("/r/engine/hooks/x/detect.py"), MANAGED), [])

    def test_fires_when_only_one_chirp_variable_is_set(self) -> None:
        env = {"CHIRP_SESSION_ID": "s1"}
        self.assertEqual(len(self.run_detect(edit("/r/engine/hooks/x/detect.py"), env)), 1)

    def test_silent_on_unrelated_path(self) -> None:
        self.assertEqual(self.run_detect(edit("/r/src/app.py"), UNMANAGED), [])
        self.assertEqual(self.run_detect(edit("/r/docs/engine/hooksnotes.md"), UNMANAGED), [])

    def test_silent_on_read_tool(self) -> None:
        self.assertEqual(self.run_detect(edit("/r/engine/hooks/x/detect.py", tool="Read"), UNMANAGED), [])

    def test_nudges_once_per_session(self) -> None:
        event = edit("/r/engine/hooks/x/detect.py")
        self.assertEqual(len(self.run_detect(event, UNMANAGED)), 1)
        self.assertEqual(self.run_detect(event, UNMANAGED), [])

    def test_unreadable_state_dir_fails_open(self) -> None:
        blocker = os.path.join(self.tmp.name, "file")
        open(blocker, "w").close()
        self.state = os.path.join(blocker, "sub")
        findings = self.run_detect(edit("/r/engine/hooks/x/detect.py"), UNMANAGED)
        self.assertEqual(len(findings), 1)

    def test_malformed_tool_input_is_ignored(self) -> None:
        self.assertEqual(self.run_detect({"tool_name": "Edit", "tool_input": "x"}, UNMANAGED), [])


if __name__ == "__main__":
    unittest.main()
