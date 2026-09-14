#!/usr/bin/env python3
"""A folder that runs no tests must fail the full run, on every Python.

run_all_tests.sh runs every folder holding a file named test*.py. A helper
named like a test file makes its folder a suite with no test cases. Python
3.12+ exits 5 for that, but CI's Python 3.9 exits 0, so the empty suite
passed there silently. The runner names the folder and fails on its own
reading of the unittest output instead of trusting the exit code.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_all_tests.sh"
TOOLCHAIN_SCRIPT = REPO_ROOT / "scripts" / "ensure_node_toolchain.sh"

PASSING_SUITE = """import unittest


class Trivial(unittest.TestCase):
    def test_true(self):
        self.assertTrue(True)
"""

HELPER_NAMED_LIKE_A_TEST = """import unittest


class SharedBase(unittest.TestCase):
    pass
"""


def _fake_repo(root: Path, *, with_empty_suite: bool) -> Path:
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "run_all_tests.sh")
    shutil.copy2(TOOLCHAIN_SCRIPT, root / "scripts" / "ensure_node_toolchain.sh")
    (root / "tests").mkdir()
    (root / "tests" / "test_trivial.py").write_text(PASSING_SUITE, encoding="utf-8")
    if with_empty_suite:
        (root / "lib").mkdir()
        (root / "lib" / "testing.py").write_text(HELPER_NAMED_LIKE_A_TEST, encoding="utf-8")
    return root


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "run_all_tests.sh")],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestEmptySuite(unittest.TestCase):
    def test_folder_that_runs_no_tests_fails_the_run_and_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(_fake_repo(Path(tmp) / "repo", with_empty_suite=True))
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("run_all_tests: ./lib ran no tests", output)

    def test_folders_with_real_tests_still_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(_fake_repo(Path(tmp) / "repo", with_empty_suite=False))
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ran no tests", output)


if __name__ == "__main__":
    unittest.main()
