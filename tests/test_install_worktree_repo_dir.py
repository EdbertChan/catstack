#!/usr/bin/env python3
"""install.sh warns, loudly, when it is linking out of a git worktree.

Real failure this pins: ~/.claude/hooks/split-scope pointed at
catstack-wt-pr450-fix/engine/hooks/split-scope. That worktree was deleted, so
the hook could not run for an entire session and reported nothing at all.

Linking against its own checkout is deliberate (see install.sh's header and
tests/test_install.py), because installing from a worktree is how a branch gets
tested. So this asserts the warning, never a redirect; hook-freshness's
unresolvable-hook sweep is what catches the link after the worktree is gone.

The fixture is a synthetic repo holding a copy of the working-tree install.sh,
so the test exercises the file as it stands now rather than whatever is at HEAD,
and passes whether the suite itself runs from the main checkout or a worktree.

Run: python3 -m unittest tests.test_install_worktree_repo_dir -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.sh")
NOTICE = "installing from a git worktree"


def git(args, cwd, timeout=60):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout,
    )


def run_help(script):
    return subprocess.run(
        ["bash", script, "--help"], capture_output=True, text=True, check=False, timeout=60,
    )


class TestInstallResolvesMainCheckout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="catstack-install-worktree-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.main = os.path.join(self.tmp, "main")
        os.makedirs(self.main)
        shutil.copy2(INSTALL, os.path.join(self.main, "install.sh"))
        for args in (
            ["init", "--quiet", "-b", "main"],
            ["config", "user.email", "probe@example.invalid"],
            ["config", "user.name", "probe"],
            ["add", "install.sh"],
            ["commit", "--quiet", "-m", "probe"],
        ):
            result = git(args, self.main)
            if result.returncode != 0:
                self.skipTest(f"could not build the probe repo: git {args[0]}: {result.stderr.strip()}")
        self.main_real = os.path.realpath(self.main)

    def test_the_main_checkout_does_not_warn(self):
        result = run_help(os.path.join(self.main, "install.sh"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(NOTICE, result.stdout)

    def test_a_worktree_warns_and_names_the_main_checkout(self):
        wt = os.path.join(self.tmp, "wt")
        added = git(["worktree", "add", "--quiet", "--detach", wt, "HEAD"], self.main)
        if added.returncode != 0:
            self.skipTest(f"could not create a probe worktree: {added.stderr.strip()}")
        result = run_help(os.path.join(wt, "install.sh"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(NOTICE, result.stdout)
        self.assertIn(f"main checkout:  {self.main_real}", result.stdout)
        self.assertIn(f"worktree:       {wt}", result.stdout)
        self.assertIn("dies when the worktree is removed", result.stdout)

    def test_outside_any_git_repo_it_stays_quiet(self):
        loose = os.path.join(self.tmp, "loose")
        os.makedirs(loose)
        shutil.copy2(INSTALL, os.path.join(loose, "install.sh"))
        result = run_help(os.path.join(loose, "install.sh"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(NOTICE, result.stdout)


if __name__ == "__main__":
    unittest.main()
