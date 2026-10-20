#!/usr/bin/env python3
"""reflect_worktrees_clean.py says dirty or unchecked before a hand-back says done.

Fail-before this script: a reflect worktree kept four modified files after the
apply agent copied its edits elsewhere, and the parent reported the PR as open
with nothing checking the tree. The unchecked outcome is pinned as a non-pass
because a path that is not a worktree cannot be called clean.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import reflect_worktrees_clean as rwc  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "reflect_worktrees_clean.py")
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True, env=GIT_ENV)


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, check=False, env=GIT_ENV)


class TempRepo:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self.tmp.name)
        self.main = os.path.join(root, "main")
        os.makedirs(self.main)
        git(self.main, "init", "-q", "-b", "main")
        with open(os.path.join(self.main, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("hello\n")
        git(self.main, "add", "README.md")
        git(self.main, "commit", "-q", "-m", "init")
        self.worktree = os.path.join(root, ".worktrees", "reflect-demo")
        git(self.main, "worktree", "add", "-q", "-b", "reflect/demo", self.worktree)
        self.plain_dir = os.path.join(root, "not-a-worktree")
        os.makedirs(self.plain_dir)
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()
        return False


class TestOutcomes(unittest.TestCase):
    def test_clean_worktree_exits_0(self):
        with TempRepo() as repo:
            res = run(repo.worktree)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn(f"clean\t{repo.worktree}", res.stdout)

    def test_dirty_worktree_exits_1_and_lists_the_paths(self):
        with TempRepo() as repo:
            with open(os.path.join(repo.worktree, "README.md"), "a", encoding="utf-8") as handle:
                handle.write("edit\n")
            with open(os.path.join(repo.worktree, "leftover.py"), "w", encoding="utf-8") as handle:
                handle.write("x = 1\n")
            res = run(repo.worktree)
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn(f"dirty\t{repo.worktree}", res.stdout)
            self.assertIn("M README.md", res.stdout)
            self.assertIn("?? leftover.py", res.stdout)

    def test_path_that_is_not_a_worktree_exits_2_as_unchecked(self):
        with TempRepo() as repo:
            res = run(repo.plain_dir)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn(f"unchecked\t{repo.plain_dir}", res.stdout)

    def test_subdirectory_of_a_worktree_is_unchecked_not_clean(self):
        with TempRepo() as repo:
            sub = os.path.join(repo.worktree, "sub")
            os.makedirs(sub)
            self.assertEqual(rwc.check(sub)[0], rwc.UNCHECKED)

    def test_unchecked_outranks_dirty_which_outranks_clean(self):
        self.assertEqual(rwc.verdict([rwc.CLEAN, rwc.DIRTY, rwc.UNCHECKED]), rwc.UNCHECKED)
        self.assertEqual(rwc.verdict([rwc.CLEAN, rwc.DIRTY]), rwc.DIRTY)
        self.assertEqual(rwc.verdict([rwc.CLEAN, rwc.CLEAN]), rwc.CLEAN)

    def test_default_discovers_reflect_worktrees_of_the_repo_root(self):
        with TempRepo() as repo:
            self.assertEqual([os.path.realpath(p) for p in rwc.discover(repo.main)], [repo.worktree])
            res = run("--repo-root", repo.main)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("reflect-demo", res.stdout)


if __name__ == "__main__":
    unittest.main()
