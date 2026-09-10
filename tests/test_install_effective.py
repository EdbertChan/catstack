#!/usr/bin/env python3
"""scripts/check_install_effective.py verifies a real installation.

Its subject is $HOME. install.sh's own suite runs against a throwaway HOME,
where nothing is installed and no harness is authenticated, so the checker
must report a skip there instead of manufacturing drift and failing the
installer with exit 4.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "check_install_effective.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from git_test_repo import disable_background_maintenance, init_repo  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin",
}
WORKTREE_NAME = "tz-wakeup"


def load_with_home(home, script=SCRIPT):
    """Import a fresh copy of the checker bound to ``home``.

    The module resolves HOME at import time, so a test that wants a different
    HOME needs its own module instance rather than a mutated global.
    """
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location("check_install_effective_under_test", str(script))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env=GIT_ENV,
    )


def build_installation(tmp, link_into_worktree):
    """A primary checkout, a worktree of it, and a $HOME linked into one of them.

    The checker copy lives inside the fixture checkout so its own
    ``git rev-parse --git-common-dir`` lookup resolves to the fixture's
    primary checkout rather than to this repository.
    """
    repo = Path(tmp) / "primary"
    init_repo(repo, "-b", "main")
    (repo / "scripts").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "check_install_effective.py")
    (repo / "corpus/skills/cat-mode").mkdir(parents=True)
    (repo / "corpus/skills/cat-mode/SKILL.md").write_text("skill", encoding="utf-8")
    (repo / "engine/hooks").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("rules", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    worktree = repo / ".worktrees" / WORKTREE_NAME
    _git(repo, "worktree", "add", "-q", "-b", WORKTREE_NAME, str(worktree))

    source = worktree if link_into_worktree else repo
    home = Path(tmp) / "home"
    (home / ".claude/skills").mkdir(parents=True)
    (home / ".claude/settings.json").write_text("{}", encoding="utf-8")
    (home / ".claude/CLAUDE.md").symlink_to(source / "CLAUDE.md")
    (home / ".claude/skills/cat-mode").symlink_to(source / "corpus/skills/cat-mode")
    return repo, home


def run_installed_checker(repo, home):
    """The checker's exit code and output for a fixture that is not a sandbox.

    ``sandbox_reason`` and the canary both refuse to judge a throwaway HOME on
    purpose, so a fixture has to stand in for the real machine at both seams.
    """
    module = load_with_home(home, repo / "scripts" / "check_install_effective.py")
    module.sandbox_reason = lambda: None
    module.check_canary = lambda: ([], [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main()
    return code, out.getvalue()


class TestSandboxHomeIsSkippedNotFailed(unittest.TestCase):
    def test_a_throwaway_home_is_named_as_a_sandbox(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            reason = module.sandbox_reason()
            self.assertIsNotNone(reason)
            self.assertIn(home, reason)

    def test_the_users_own_home_is_checked_for_real(self):
        real_home = pwd.getpwuid(os.getuid()).pw_dir
        module = load_with_home(real_home)
        self.assertIsNone(module.sandbox_reason())

    def test_script_exits_zero_and_prints_skip_for_a_sandbox_home(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                [sys.executable, SCRIPT],
                env={**os.environ, "HOME": home},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skip:", result.stdout)
            self.assertNotIn("Installation is not in effect", result.stdout)


class TestCanaryCannotManufactureDrift(unittest.TestCase):
    def test_a_missing_claude_cli_is_unverifiable_not_drift(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            claude_dir = Path(home) / ".claude"
            claude_dir.mkdir()
            source = Path(home) / "CLAUDE.md"
            source.write_text("rules", encoding="utf-8")
            (claude_dir / "CLAUDE.md").symlink_to(source)
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(Path(home) / "no-binaries-here")
            try:
                drift, unverifiable = module.check_canary()
            finally:
                os.environ["PATH"] = previous_path
        self.assertEqual(drift, [])
        self.assertEqual(len(unverifiable), 1)
        self.assertIn("canary could not run", unverifiable[0])

    def test_an_unlinked_claude_md_leaves_the_canary_silent(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            self.assertEqual(module.check_canary(), ([], []))

    def canary_with_answer(self, answer):
        """check_canary against a fake `claude` CLI that prints ``answer``."""
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            claude_dir = Path(home) / ".claude"
            claude_dir.mkdir()
            source = Path(home) / "CLAUDE.md"
            source.write_text("rules", encoding="utf-8")
            (claude_dir / "CLAUDE.md").symlink_to(source)
            bin_dir = Path(home) / "bin"
            bin_dir.mkdir()
            (Path(home) / "answer.txt").write_text(answer, encoding="utf-8")
            fake = bin_dir / "claude"
            fake.write_text(f"#!/bin/sh\ncat '{Path(home) / 'answer.txt'}'\n", encoding="utf-8")
            fake.chmod(0o755)
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bin_dir}:/usr/bin:/bin"
            try:
                return module.check_canary()
            finally:
                os.environ["PATH"] = previous_path

    def test_a_prose_answer_is_unverifiable_not_drift(self):
        """A Stop hook can swap the one-word answer for a report containing "not"."""
        drift, unverifiable = self.canary_with_answer(
            "I did not run reflect. The hook fired on a false alarm.\n"
            "Accepted: none.\n"
        )
        self.assertEqual(drift, [])
        self.assertEqual(len(unverifiable), 1)
        self.assertIn("no one-word YES/NO answer", unverifiable[0])

    def test_a_one_word_no_is_drift(self):
        drift, unverifiable = self.canary_with_answer("NO.\n")
        self.assertEqual(unverifiable, [])
        self.assertEqual(len(drift), 1)
        self.assertIn("NOT loaded", drift[0])

    def test_a_one_word_yes_is_clean(self):
        self.assertEqual(self.canary_with_answer("**Yes**\n"), ([], []))


class TestLinksIntoAWorktreeAreDrift(unittest.TestCase):
    def test_links_resolving_into_a_worktree_fail_and_name_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=True)
            code, output = run_installed_checker(repo, home)
        self.assertNotEqual(code, 0, output)
        self.assertIn("worktree", output)
        self.assertIn(WORKTREE_NAME, output)
        self.assertIn(str(repo / ".worktrees" / WORKTREE_NAME), output)
        self.assertIn("2 link", output)
        self.assertIn(str(Path(home) / ".claude"), output)

    def test_links_resolving_into_the_primary_checkout_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 0, output)
        self.assertNotIn(WORKTREE_NAME, output)

    def test_an_unregistered_hook_still_fails_when_no_link_is_in_a_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            hook = repo / "engine/hooks/demo-freeze"
            hook.mkdir(parents=True)
            (hook / "claude.hook.json").write_text("{}", encoding="utf-8")
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn("hook built but never registered", output)


def relink_claude_md(home, source):
    link = Path(home) / ".claude/CLAUDE.md"
    link.unlink()
    link.symlink_to(Path(source) / "CLAUDE.md")


class TestLinksIntoAnotherCloneOfTheRepo(unittest.TestCase):
    """The checker can run from a clone other than the one installed.

    An Invoker or CI clone runs it while $HOME links into the user's own
    checkout. That checkout is a real installation of the same repository.
    """

    def test_a_primary_checkout_of_the_same_repository_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            clone = Path(tmp) / "users-own-checkout"
            subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
            disable_background_maintenance(clone)
            relink_claude_md(home, clone)
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 0, output)
        self.assertNotIn("points outside the repo", output)

    def test_a_checkout_of_an_unrelated_repository_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            other = Path(tmp) / "unrelated"
            init_repo(other, "-b", "main")
            (other / "CLAUDE.md").write_text("other rules", encoding="utf-8")
            _git(other, "add", "-A")
            _git(other, "commit", "-q", "-m", "unrelated baseline")
            relink_claude_md(home, other)
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn("points outside the repo", output)
        self.assertIn("shares no root commit", output)

    def test_a_worktree_of_another_clone_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            clone = Path(tmp) / "users-own-checkout"
            subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
            disable_background_maintenance(clone)
            worktree = Path(tmp) / "elsewhere" / "branch"
            _git(clone, "worktree", "add", "-q", "-b", "branch", str(worktree))
            relink_claude_md(home, worktree)
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn("points outside the repo", output)
        self.assertIn("is a git worktree, not a primary checkout", output)

    def test_a_link_outside_any_checkout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            loose = Path(tmp) / "loose"
            loose.mkdir()
            (loose / "CLAUDE.md").write_text("loose rules", encoding="utf-8")
            relink_claude_md(home, loose)
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn("points outside the repo", output)
        self.assertIn("could not be read", output)


class TestWorktreeRootNaming(unittest.TestCase):
    def test_a_resolved_path_inside_a_worktree_names_that_worktree(self):
        module = load_with_home(pwd.getpwuid(os.getuid()).pw_dir)
        found = module.worktree_root(Path("/repo/.worktrees/tz-wakeup/corpus/skills/reflect"))
        self.assertEqual(found, Path("/repo/.worktrees/tz-wakeup"))

    def test_a_resolved_path_in_the_primary_checkout_names_no_worktree(self):
        module = load_with_home(pwd.getpwuid(os.getuid()).pw_dir)
        self.assertIsNone(module.worktree_root(Path("/repo/corpus/skills/reflect")))


class TestUnreadableLinksAreNotReportedClean(unittest.TestCase):
    def test_a_missing_claude_dir_is_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            problems, unverifiable = module.check_worktree_links()
        self.assertEqual(problems, [])
        self.assertEqual(len(unverifiable), 1)
        self.assertIn("unchecked", unverifiable[0])


if __name__ == "__main__":
    unittest.main()
