#!/usr/bin/env python3
"""Tests for scripts/check_no_new_comments.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_no_new_comments as cc  # noqa: E402

REAL_HUNK = """diff --git a/engine/hooks/diu-stop/claude_stop_check.py b/engine/hooks/diu-stop/claude_stop_check.py
--- a/engine/hooks/diu-stop/claude_stop_check.py
+++ b/engine/hooks/diu-stop/claude_stop_check.py
@@ -112,0 +113,5 @@
+    if data.get("stop_hook_active"):
+        # This block already fired once this turn and the agent has rewritten.
+        # Let the rewrite through: a second block starts a shave-a-few-words
+        return
"""


class TestFlags(unittest.TestCase):
    def test_flags_real_added_comment_lines(self):
        problems = cc.check(REAL_HUNK)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("claude_stop_check.py", problems[0])


class TestStaysSilent(unittest.TestCase):
    def test_silent_on_removed_comments_and_added_code(self):
        diff = "+++ b/a.py\n-# old comment\n+x = 1  # noqa\n+y = 2\n"
        self.assertEqual(cc.check(diff), [])

    def test_silent_on_markdown_and_yaml(self):
        diff = "+++ b/README.md\n+# Title\n+++ b/.github/workflows/ci.yml\n+# yaml comment\n"
        self.assertEqual(cc.check(diff), [])


if __name__ == "__main__":
    unittest.main()
