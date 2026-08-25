#!/usr/bin/env python3
"""Unit tests for the demo-surface freeze PreToolUse hook.

Run: python3 -m unittest discover -s hooks/demo-freeze/tests -v
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse_check  # noqa: E402


def run_hook(marker_lines, tool_input, marker_age_secs=0):
    marker = tempfile.NamedTemporaryFile(mode="w", suffix=".freeze", delete=False)
    marker.write("\n".join(marker_lines) + "\n")
    marker.close()
    if marker_age_secs:
        old = time.time() - marker_age_secs
        os.utime(marker.name, (old, old))
    err = io.StringIO()
    payload = {"tool_name": "Edit", "tool_input": tool_input}
    try:
        with patch.object(claude_pretooluse_check, "MARKER", marker.name):
            with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with redirect_stderr(err):
                    try:
                        claude_pretooluse_check.main()
                    except SystemExit as e:
                        return e.code == 2, err.getvalue()
        return False, err.getvalue()
    finally:
        os.unlink(marker.name)


class TestDemoFreeze(unittest.TestCase):
    def test_exact_path_blocks(self):
        blocked, err = run_hook(["/tmp/demo/call.html"], {"file_path": "/tmp/demo/call.html"})
        self.assertTrue(blocked)
        self.assertIn("Demo surface frozen", err)

    def test_directory_prefix_blocks(self):
        blocked, _ = run_hook(["/tmp/demo/"], {"file_path": "/tmp/demo/nested/page.html"})
        self.assertTrue(blocked)

    def test_glob_blocks(self):
        blocked, _ = run_hook(["/tmp/demo/*.html"], {"file_path": "/tmp/demo/call.html"})
        self.assertTrue(blocked)

    def test_unrelated_path_passes(self):
        blocked, _ = run_hook(["/tmp/demo/"], {"file_path": "/repo/src/main.py"})
        self.assertFalse(blocked)

    def test_comments_and_blanks_ignored(self):
        blocked, _ = run_hook(["# frozen for the demo", "", "/tmp/demo/"], {"file_path": "/repo/src/main.py"})
        self.assertFalse(blocked)

    def test_stale_marker_auto_expires(self):
        blocked, _ = run_hook(["/tmp/demo/"], {"file_path": "/tmp/demo/call.html"},
                              marker_age_secs=3 * 3600)
        self.assertFalse(blocked)

    def test_no_marker_fails_open(self):
        err = io.StringIO()
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/demo/call.html"}}
        with patch.object(claude_pretooluse_check, "MARKER", "/nonexistent/.demo-freeze"):
            with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with redirect_stderr(err):
                    claude_pretooluse_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_non_file_tool_input_passes(self):
        blocked, _ = run_hook(["/tmp/demo/"], {"command": "ls"})
        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
