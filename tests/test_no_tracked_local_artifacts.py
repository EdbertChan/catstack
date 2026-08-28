#!/usr/bin/env python3
"""Focused tests for the tracked local-artifact policy."""
from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_tracked_local_artifacts.py"
sys.path.insert(0, str(REPO / "scripts"))
import check_no_tracked_local_artifacts as checker  # noqa: E402


class TestForbiddenTrackedPaths(unittest.TestCase):
    def test_returns_only_forbidden_paths(self):
        paths = [
            ".worktrees/topic/checkout.txt",
            "package/__pycache__/module.cpython-313.pyc",
            "compiled/module.pyc",
            "docs/keep.txt",
        ]

        self.assertEqual(
            checker.forbidden_tracked_paths(paths),
            paths[:3],
        )

    def test_ignores_lookalike_paths(self):
        paths = [
            ".worktrees-not/topic/checkout.txt",
            "nested/.worktrees/checkout.txt",
            "package/__pycache___/module.py",
            "package/cache.pyc.txt",
            "docs/pyc",
        ]

        self.assertEqual(checker.forbidden_tracked_paths(paths), [])

    def test_current_repository_index_is_clean(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            checker.forbidden_tracked_paths(result.stdout.splitlines()),
            [],
        )

    def test_executable_rejects_forbidden_tracked_paths(self):
        inventory = "src/__pycache__/module.pyc\n.worktrees/topic/file.txt\n"
        git_result = subprocess.CompletedProcess(
            ["git", "ls-files"],
            returncode=0,
            stdout=inventory,
            stderr="",
        )
        output = io.StringIO()

        with mock.patch.object(checker.subprocess, "run", return_value=git_result):
            with redirect_stdout(output):
                exit_code = checker.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("check_no_tracked_local_artifacts: FAIL", output.getvalue())
        self.assertIn("src/__pycache__/module.pyc", output.getvalue())
        self.assertIn(".worktrees/topic/file.txt", output.getvalue())
        self.assertIn("Remove the listed paths from the Git index", output.getvalue())

    def test_executable_reports_clean_index(self):
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "check_no_tracked_local_artifacts: OK\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
