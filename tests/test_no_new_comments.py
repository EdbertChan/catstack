#!/usr/bin/env python3
"""Tests for scripts/check_no_new_comments.py."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_no_new_comments as cc  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

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


MOVED_USAGE = """diff --git a/scripts/check_demo.py b/scripts/ci/check_demo.py
similarity index 98%
rename from scripts/check_demo.py
rename to scripts/ci/check_demo.py
--- a/scripts/check_demo.py
+++ b/scripts/ci/check_demo.py
@@ -3 +3 @@
-    python3 scripts/check_demo.py   # diff vs origin/main
+    python3 scripts/ci/check_demo.py   # diff vs origin/main
"""


def _only(path):
    return lambda candidate: candidate == path


class TestMovedFiles(unittest.TestCase):
    def test_silent_when_a_line_only_follows_a_moved_file(self):
        self.assertEqual(cc.check(MOVED_USAGE, exists=_only("scripts/ci/check_demo.py")), [])

    def test_flags_a_moved_line_that_also_adds_comment_words(self):
        diff = MOVED_USAGE.replace("+    python3 scripts/ci/check_demo.py   # diff vs origin/main", "+    python3 scripts/ci/check_demo.py   # diff vs origin/main, see notes")
        self.assertEqual(len(cc.check(diff, exists=_only("scripts/ci/check_demo.py"))), 1)

    def test_flags_a_moved_line_whose_new_path_does_not_exist(self):
        self.assertEqual(len(cc.check(MOVED_USAGE, exists=lambda candidate: False)), 1)

    def test_a_file_replaced_by_a_link_to_its_new_place_reads_as_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root, "-b", "main")
            (root / "scripts").mkdir()
            (root / "scripts/tool.py").write_text("# keeps its comment\nx = 1\ny = 2\nz = 3\n", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], check=True)
            base = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            (root / "scripts/ci").mkdir()
            os.replace(root / "scripts/tool.py", root / "scripts/ci/tool.py")
            os.symlink("ci/tool.py", root / "scripts/tool.py")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            diff = cc.diff_since(base, tmp)
            exists = lambda candidate: (root / candidate).exists()
            self.assertEqual(cc.check(diff, exists=exists), [])


if __name__ == "__main__":
    unittest.main()
