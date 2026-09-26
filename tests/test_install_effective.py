#!/usr/bin/env python3
"""scripts/ci/check_install_effective.py verifies a real installation.

Its subject is $HOME. install.sh's own suite runs against a throwaway HOME,
where nothing is installed and no harness is authenticated, so the checker
must report a skip there instead of manufacturing drift and failing the
installer.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "ci", "check_install_effective.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "test"))

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


def write_hook_registry(repo):
    """The checker reads engine/hooks/hooks.toml through the _sdk registry, so a
    fixture repo needs both the loader and a registry. ``demo-freeze`` is listed
    active because write_declared_hook installs it, and check_hooks_registered
    only validates hooks the registry names as active."""
    sdk = Path(repo) / "engine/hooks/_sdk"
    sdk.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        os.path.join(REPO_ROOT, "engine/hooks/_sdk/registry.py"),
        sdk / "registry.py",
    )
    (Path(repo) / "engine/hooks/hooks.toml").write_text(
        "[hooks.demo-freeze]\n"
        'mode = "warn"\n'
        'why_mode = "habit"\n'
        'summary = "Fixture hook for the install checker tests."\n'
        "\n"
        "[thresholds]\n"
        "min_closed_findings = 30\n"
        "promote_max_ignore_rate = 0.02\n"
        "demote_min_ignore_rate = 0.10\n"
        "review_min_ignore_rate = 0.50\n"
        "review_min_unchecked_rate = 0.05\n"
        "followup_window_checks = 3\n",
        encoding="utf-8",
    )


def build_installation(tmp, link_into_worktree):
    """A primary checkout, a worktree of it, and a $HOME linked into one of them.

    The checker copy lives inside the fixture checkout so its own
    ``git rev-parse --git-common-dir`` lookup resolves to the fixture's
    primary checkout rather than to this repository.
    """
    repo = Path(tmp) / "primary"
    init_repo(repo, "-b", "main")
    (repo / "scripts" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "ci" / "check_install_effective.py")
    (repo / "engine/hooks/_runner").mkdir(parents=True)
    shutil.copy(
        os.path.join(REPO_ROOT, "engine/hooks/_runner/wrap_installed.py"),
        repo / "engine/hooks/_runner/wrap_installed.py",
    )
    write_hook_registry(repo)
    (repo / "corpus/skills/cat-mode").mkdir(parents=True)
    (repo / "corpus/skills/cat-mode/SKILL.md").write_text("skill", encoding="utf-8")
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
    module = load_with_home(home, repo / "scripts" / "ci" / "check_install_effective.py")
    module.sandbox_reason = lambda: None
    module.check_canary = lambda: ([], [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main()
    return code, out.getvalue()


def hook_entry(command):
    return [{"matcher": "", "hooks": [{"type": "command", "command": command}]}]


def write_settings(home, hooks):
    (Path(home) / ".claude/settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")


def write_declared_hook(repo, event="UserPromptSubmit", command="$HOME/.claude/hooks/demo-freeze/run.py"):
    hook = Path(repo) / "engine/hooks/demo-freeze"
    hook.mkdir(parents=True)
    (hook / "claude.hook.json").write_text(
        json.dumps({"hooks": {event: hook_entry(command)}}),
        encoding="utf-8",
    )
    return "demo-freeze", event, command


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

    def test_a_declared_hook_command_under_the_wrong_event_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            hook_name, event, command = write_declared_hook(repo)
            write_settings(home, {"Stop": hook_entry(command)})
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn(hook_name, output)
        self.assertIn("claude.hook.json", output)
        self.assertIn(event, output)
        self.assertIn(command, output)

    def test_a_declared_hook_event_with_the_wrong_command_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            hook_name, event, command = write_declared_hook(repo)
            write_settings(home, {event: hook_entry("$HOME/.claude/hooks/demo-freeze/other.py")})
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn(hook_name, output)
        self.assertIn("claude.hook.json", output)
        self.assertIn(event, output)
        self.assertIn(command, output)

    def test_a_declared_hook_event_and_command_pair_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            hook_name, event, command = write_declared_hook(repo)
            write_settings(home, {event: hook_entry(command)})
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 0, output)
        self.assertNotIn(hook_name, output)
        self.assertNotIn(command, output)

    def test_an_installer_generated_skill_directory_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            installed = Path(home) / ".claude/skills/cat-mode"
            installed.unlink()
            installed.mkdir()
            (installed / ".catstack-generated").write_text("", encoding="utf-8")
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 0, output)
        self.assertNotIn("skill shadowed", output)

    def test_a_hand_made_skill_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = build_installation(tmp, link_into_worktree=False)
            installed = Path(home) / ".claude/skills/cat-mode"
            installed.unlink()
            installed.mkdir()
            code, output = run_installed_checker(repo, home)
        self.assertEqual(code, 1, output)
        self.assertIn("skill shadowed by a real directory", output)
        self.assertIn(str(installed), output)


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


HOOK_MARKER_REL = os.path.join("engine", "hooks", "diu-stop", "EFFECTIVE_TEST_MARKER")
REAL_HOME = os.path.expanduser("~")
INSTALL_TIMEOUT = 120


def build_pinned_hooks_source_repo(tmp):
    """A standalone git repo seeded from this checkout's current working tree
    (including uncommitted edits), with two commits -- A and B -- that differ
    only in HOOK_MARKER_REL. Returns (repo, sha_a, sha_b)."""
    repo = Path(tmp) / "install-source"
    init_repo(repo, "-b", "main")
    shutil.copytree(
        REPO_ROOT, repo,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )

    (repo / HOOK_MARKER_REL).write_text("A\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    sha_a = _git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / HOOK_MARKER_REL).write_text("B\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B")
    sha_b = _git(repo, "rev-parse", "HEAD").stdout.strip()

    return repo, sha_a, sha_b


def run_install_at(repo, fake_home, args=None, timeout=INSTALL_TIMEOUT):
    assert str(fake_home) != REAL_HOME, "refusing to run install.sh against the real home directory"
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "CATSTACK_REFLECT_RULE_FILE": os.path.join(str(fake_home), "reflect-enforcement.local.md"),
    }
    return subprocess.run(
        ["bash", str(Path(repo) / "install.sh")] + (args or []),
        env=env, capture_output=True, text=True, timeout=timeout,
    )


def installed_hook_marker(fake_home):
    return (Path(fake_home) / ".claude/hooks/diu-stop/EFFECTIVE_TEST_MARKER").read_text(encoding="utf-8")


def snapshot_hook_marker(fake_home):
    return (
        Path(fake_home) / ".cache/catstack-hooks-snapshot/diu-stop/EFFECTIVE_TEST_MARKER"
    ).read_text(encoding="utf-8")


class TestHooksArePinnedToTheCommitInstallRanAt(unittest.TestCase):
    """install.sh snapshots engine/hooks at the commit it runs from, instead
    of symlinking straight into the checkout -- so switching that checkout's
    branch does not silently change which hook code is live."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home_tmp = tempfile.TemporaryDirectory()
        self.repo, self.sha_a, self.sha_b = build_pinned_hooks_source_repo(self.tmp.name)
        self.fake_home = self.home_tmp.name

    def tearDown(self):
        self.home_tmp.cleanup()
        self.tmp.cleanup()

    def test_checking_out_a_newer_commit_does_not_change_the_installed_hook_until_rerun(self):
        _git(self.repo, "checkout", "-q", self.sha_a)
        first = run_install_at(self.repo, self.fake_home)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(installed_hook_marker(self.fake_home), "A\n")

        _git(self.repo, "checkout", "-q", self.sha_b)
        self.assertEqual(
            installed_hook_marker(self.fake_home), "A\n",
            "switching the source checkout's commit must not change the installed hook",
        )

        second = run_install_at(self.repo, self.fake_home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(installed_hook_marker(self.fake_home), "B\n")

    def test_rerun_on_the_same_commit_is_a_noop_and_leaves_unrelated_settings_untouched(self):
        _git(self.repo, "checkout", "-q", self.sha_a)
        settings_path = Path(self.fake_home) / ".claude/settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"model": "sonnet", "unrelated": {"nested": "value"}}), encoding="utf-8")

        first = run_install_at(self.repo, self.fake_home)
        self.assertEqual(first.returncode, 0, first.stderr)
        marker_after_first = installed_hook_marker(self.fake_home)
        settings_after_first = settings_path.read_text(encoding="utf-8")

        second = run_install_at(self.repo, self.fake_home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("relink", second.stdout)
        self.assertIn("already linked", second.stdout)
        self.assertEqual(installed_hook_marker(self.fake_home), marker_after_first)
        settings_after_second = settings_path.read_text(encoding="utf-8")
        settings = json.loads(settings_after_second)
        self.assertEqual(settings["model"], "sonnet")
        self.assertEqual(settings["unrelated"], {"nested": "value"})
        self.assertEqual(settings_after_first, settings_after_second)

    def test_rerun_on_a_newer_commit_replaces_the_snapshot(self):
        _git(self.repo, "checkout", "-q", self.sha_a)
        run_install_at(self.repo, self.fake_home)
        self.assertEqual(snapshot_hook_marker(self.fake_home), "A\n")

        _git(self.repo, "checkout", "-q", self.sha_b)
        result = run_install_at(self.repo, self.fake_home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot_hook_marker(self.fake_home), "B\n")
        self.assertEqual(installed_hook_marker(self.fake_home), "B\n")

    def test_a_failed_copy_keeps_the_previous_snapshot(self):
        _git(self.repo, "checkout", "-q", self.sha_a)
        first = run_install_at(self.repo, self.fake_home)
        self.assertEqual(first.returncode, 0, first.stderr)
        unreadable = Path(self.repo) / HOOK_MARKER_REL
        os.chmod(unreadable, 0)
        try:
            second = run_install_at(self.repo, self.fake_home)
        finally:
            os.chmod(unreadable, 0o644)

        self.assertNotEqual(second.returncode, 0, second.stdout)
        self.assertIn("the current snapshot is unchanged", second.stderr)
        self.assertEqual(snapshot_hook_marker(self.fake_home), "A\n")
        self.assertEqual(installed_hook_marker(self.fake_home), "A\n")

    def test_the_source_record_names_checkout_commit_and_branch(self):
        _git(self.repo, "checkout", "-q", "main")
        result = run_install_at(self.repo, self.fake_home)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = Path(self.fake_home) / ".cache/catstack-hooks-snapshot/.catstack-source"
        self.assertEqual(
            record.read_text(encoding="utf-8").splitlines(),
            [str(self.repo), self.sha_b, "main"],
        )

    def test_the_snapshot_is_swapped_in_by_one_rename_and_old_versions_are_pruned(self):
        _git(self.repo, "checkout", "-q", self.sha_a)
        for _ in range(3):
            result = run_install_at(self.repo, self.fake_home)
            self.assertEqual(result.returncode, 0, result.stderr)
        live = Path(self.fake_home) / ".cache/catstack-hooks-snapshot"
        versions = Path(self.fake_home) / ".cache/catstack-hooks-snapshots"
        self.assertTrue(live.is_symlink())
        self.assertEqual(live.resolve().parent, versions.resolve())
        self.assertLessEqual(len(list(versions.iterdir())), 2)
        self.assertFalse(Path(f"{live}.swap").exists())


if __name__ == "__main__":
    unittest.main()
