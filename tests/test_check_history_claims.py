#!/usr/bin/env python3
"""Tests for scripts/check_history_claims.py input handling.

The no-argument form used to read stdin. Under a runner that hands the
process an open pipe it never closes, that read never returned and the
verify command sat until the 14400s runner limit killed it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_history_claims.py"
sys.path.insert(0, str(REPO / "scripts"))
from git_test_repo import init_repo  # noqa: E402

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=GIT_ENV)


class TestNoArgsScansBranchProse(unittest.TestCase):
    """Throwaway repo: base commit on main, then a feature branch."""

    def _repo(self, tmp: str, markdown: str, code: str = "") -> Path:
        repo = Path(tmp)
        init_repo(repo, "-b", "main")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "check_history_claims.py").write_text(SCRIPT.read_text())
        (repo / "notes.md").write_text("# notes\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        _git(repo, "checkout", "-qb", "feature")
        (repo / "notes.md").write_text("# notes\n" + markdown)
        if code:
            (repo / "tool.py").write_text(code)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "change")
        return repo

    def _run_with_open_stdin(self, repo: Path) -> tuple[int, str]:
        proc = subprocess.Popen(
            [sys.executable, str(repo / "scripts" / "check_history_claims.py"), "--base", "main"],
            cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail("no-argument run blocked on an open stdin pipe")
        finally:
            proc.stdin.close()
        out = proc.stdout.read()
        proc.stdout.close()
        return code, out

    def test_returns_with_open_stdin_and_passes_clean_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "The function returns a list.\n")
            code, out = self._run_with_open_stdin(repo)
            self.assertEqual(code, 0, out)
            self.assertIn("1 added markdown line", out)

    def test_flags_added_markdown_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "This bug has existed for five months.\n")
            code, out = self._run_with_open_stdin(repo)
            self.assertEqual(code, 1, out)
            self.assertIn("notes.md:1: duration claim", out)

    def test_ignores_claim_shaped_strings_in_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "", code='EXEMPLAR = "this bug has existed for five months"\n')
            code, out = self._run_with_open_stdin(repo)
            self.assertEqual(code, 0, out)

    def test_unresolvable_base_is_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "The function returns a list.\n")
            result = subprocess.run(
                [sys.executable, str(repo / "scripts" / "check_history_claims.py"), "--base", "no-such-ref"],
                cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("unchecked", result.stderr)
            self.assertNotIn("OK", result.stdout)


class TestExplicitInputs(unittest.TestCase):
    def test_dash_reads_stdin(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "-"], input="three sessions found this pattern\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stdin:1: count claim", result.stdout)

    def test_missing_file_is_unchecked_not_clean(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "/nonexistent/pr-body.md"], capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unchecked", result.stderr)
        self.assertNotIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
