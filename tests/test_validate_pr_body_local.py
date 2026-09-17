#!/usr/bin/env python3
"""Tests for scripts/pr/validate-pr-body-local.mjs.

Each case copies the checker and the two scripts it calls into a throwaway
repo, so preflight.py reads that repo's diff and the validator runs with no
node_modules beside it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "test"))

from git_test_repo import init_repo  # noqa: E402

COPIED = (
    "drafter.config.json",
    "scripts/pr/validate-pr-body-local.mjs",
    "engine/skills/make-pr/scripts/preflight.py",
    "engine/skills/draft-pr/scripts/validate-pr-body.mjs",
    "engine/skills/draft-pr/scripts/drafter-core-flag.mjs",
    "engine/skills/draft-pr/scripts/summary-reading-grade.mjs",
    "engine/hooks/_flags/flags.py",
)
UNCHECKED = "UNCHECKED: PR body rules not checked (drafter-core not installed)"
SKIPPED = "UNCHECKED: drafter-core rules skipped (CATSTACK_DRAFTER_CORE is off"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "CATSTACK_DRAFTER_CORE": "1",
}


class TestValidatePrBodyLocal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.body = Path(self._tmp.name) / "body.md"
        self.body.write_text("## Summary\n\nA change.\n", encoding="utf-8")
        init_repo(self.repo, "-b", "main", env=GIT_ENV)
        for rel in COPIED:
            dest = self.repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        self._git("add", "-A")
        self._git("commit", "-qm", "base")
        self._git("checkout", "-qb", "feature")

    def _git(self, *args: str) -> None:
        res = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, env=GIT_ENV)
        self.assertEqual(res.returncode, 0, f"git {' '.join(args)}: {res.stderr}")

    def _commit(self, *paths: str) -> None:
        for rel in paths:
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "case")

    def _run(self, *args: str, flag: str = "1") -> subprocess.CompletedProcess:
        return subprocess.run(
            ["node", "scripts/pr/validate-pr-body-local.mjs", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={**GIT_ENV, "CATSTACK_DRAFTER_CORE": flag},
        )

    def test_mixed_review_units_fail_with_split(self):
        self._commit("engine/hooks/x/detect.py", "product/skills/y/SKILL.md")
        res = self._run("--body-file", str(self.body), "--base", "main")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("split", res.stdout)

    def test_one_unit_without_drafter_core_fails_as_unchecked(self):
        self._commit("engine/hooks/x/detect.py")
        res = self._run("--body-file", str(self.body), "--base", "main")
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn(UNCHECKED, res.stdout)

    def test_flag_off_skips_drafter_core_and_exits_unchecked(self):
        self._commit("engine/hooks/x/detect.py")
        res = self._run("--body-file", str(self.body), "--base", "main", flag="0")
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn(SKIPPED, res.stdout)
        self.assertNotIn("ERR_MODULE_NOT_FOUND", res.stderr)

    def test_checkout_without_unit_rules_fails_as_unchecked(self):
        self._git("rm", "-q", "drafter.config.json")
        self._commit("engine/hooks/x/detect.py")
        res = self._run("--body-file", str(self.body), "--base", "main")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("unchecked review units", res.stdout)
        self.assertIn("preflight.py exited 3", res.stderr)

    def test_missing_body_file_is_usage_error(self):
        self._commit("engine/hooks/x/detect.py")
        res = self._run("--base", "main")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("Usage:", res.stderr)

    def test_absent_body_file_is_usage_error_not_unchecked(self):
        self._commit("engine/hooks/x/detect.py")
        res = self._run("--body-file", str(self.body) + ".missing", "--base", "main")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertNotIn(UNCHECKED, res.stdout)
        self.assertIn("Body file not found", res.stderr)


if __name__ == "__main__":
    unittest.main()
