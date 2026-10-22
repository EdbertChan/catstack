#!/usr/bin/env python3
"""Positive, negative and unchecked cases for check_skill_install_drift.

Fixtures are throwaway git repos built here, not by the gate's own exemplar
helper, so a bug in that helper cannot vouch for itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
sys.path.insert(0, str(REPO / "scripts" / "test"))
import check_skill_install_drift as gate  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

CHECK = REPO / "scripts" / "ci" / "check_skill_install_drift.py"
SKILL_REL = Path("product") / "skills" / "demo" / "SKILL.md"
SEED = "---\nname: demo\n---\n\n# demo\n\n- rule one\n"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=ENV)


def _seed_repo(tmp: str) -> Path:
    root = Path(tmp) / "repo"
    init_repo(root, env=ENV)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(root, "config", key, value)
    (root / SKILL_REL).parent.mkdir(parents=True)
    (root / SKILL_REL).write_text(SEED, encoding="utf-8")
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _swap_for_symlink(root: Path, tmp: str, body: str) -> Path:
    private = Path(tmp) / "home" / ".claude" / "local" / "demo" / "SKILL.md"
    private.parent.mkdir(parents=True)
    private.write_text(body, encoding="utf-8")
    (root / SKILL_REL).unlink()
    os.symlink(private, root / SKILL_REL)
    return private


class DriftIsCaught(unittest.TestCase):
    def test_symlink_to_a_private_copy_with_extra_lines_names_skill_path_and_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            private = _swap_for_symlink(root, tmp, SEED + "- rule two\n- rule three\n")
            problems = gate.check(str(root))
        self.assertEqual(1, len(problems), problems)
        self.assertTrue(problems[0].startswith("drift"), problems[0])
        self.assertIn("demo:", problems[0])
        self.assertIn(str(SKILL_REL), problems[0])
        self.assertIn(str(private.resolve()), problems[0])
        self.assertIn("+2/-0 lines", problems[0])

    def test_skip_worktree_bit_is_drift_even_when_bytes_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            _git(root, "update-index", "--skip-worktree", str(SKILL_REL))
            problems = gate.check(str(root))
        self.assertEqual(1, len(problems), problems)
        self.assertIn("skip-worktree set (git ls-files -v flag S)", problems[0])

    def test_assume_unchanged_bit_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            _git(root, "update-index", "--assume-unchanged", str(SKILL_REL))
            problems = gate.check(str(root))
        self.assertEqual(1, len(problems), problems)
        self.assertIn("assume-unchanged set (git ls-files -v flag h)", problems[0])

    def test_edited_tracked_skill_file_counts_removed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            (root / SKILL_REL).write_text(SEED.replace("- rule one\n", ""), encoding="utf-8")
            problems = gate.check(str(root))
        self.assertEqual(1, len(problems), problems)
        self.assertIn("+0/-1 lines", problems[0])

    def test_cli_exits_one_and_prints_the_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            _swap_for_symlink(root, tmp, SEED + "- rule two\n")
            _git(root, "update-index", "--skip-worktree", str(SKILL_REL))
            result = subprocess.run(
                [sys.executable, str(CHECK), "--repo", str(root)], capture_output=True, text=True, timeout=60
            )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FAIL 2 drifted, 0 unchecked of 1 tracked skill file(s)", result.stderr)


class CleanTreesPass(unittest.TestCase):
    def test_tree_that_matches_head_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            self.assertEqual([], gate.check(str(root)))

    def test_symlink_whose_target_has_identical_bytes_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            _swap_for_symlink(root, tmp, SEED)
            self.assertEqual([], gate.check(str(root)))

    def test_edits_outside_the_skill_roots_are_not_compared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            (root / "README.md").write_text("# changed\n", encoding="utf-8")
            (root / SKILL_REL.parent / "scratch.md").write_text("untracked\n", encoding="utf-8")
            self.assertEqual([], gate.check(str(root)))

    def test_cli_exits_zero_on_a_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            result = subprocess.run(
                [sys.executable, str(CHECK), "--repo", str(root)], capture_output=True, text=True, timeout=60
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("ok      skill install drift: 1 tracked skill file(s)", result.stdout)


class UnreadableInputIsUncheckedNotClean(unittest.TestCase):
    def test_dangling_symlink_is_unchecked_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _seed_repo(tmp)
            (root / SKILL_REL).unlink()
            os.symlink(Path(tmp) / "gone" / "SKILL.md", root / SKILL_REL)
            problems = gate.check(str(root))
            result = subprocess.run(
                [sys.executable, str(CHECK), "--repo", str(root)], capture_output=True, text=True, timeout=60
            )
        self.assertEqual(1, len(problems), problems)
        self.assertTrue(problems[0].startswith("unchecked"), problems[0])
        self.assertIn("FileNotFoundError", problems[0])
        self.assertEqual(1, result.returncode)
        self.assertIn("FAIL 0 drifted, 1 unchecked", result.stderr)

    def test_directory_that_is_not_a_git_checkout_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = gate.check(tmp)
        self.assertEqual(1, len(problems), problems)
        self.assertTrue(problems[0].startswith("unchecked"), problems[0])
        self.assertIn("git ls-files failed", problems[0])


class GateIsWired(unittest.TestCase):
    def test_ci_workflow_runs_the_gate(self):
        text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python3 scripts/ci/check_skill_install_drift.py", text)


if __name__ == "__main__":
    unittest.main()
