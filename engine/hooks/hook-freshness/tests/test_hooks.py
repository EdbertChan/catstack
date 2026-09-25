#!/usr/bin/env python3
"""Tests for the hook-freshness UserPromptSubmit hook.

Run: python3 -m unittest discover -s engine/hooks/hook-freshness/tests -v

Git is injected as a fake runner, so no test touches a real repo or the
network. The stale case mirrors the real failure: the checkout behind the
live symlinks on a feature branch, dozens of commits behind origin/main,
with merged hook fixes therefore not installed.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "test"))

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True, env=GIT_ENV,
    )


def _write_marker(snapshot, repo, sha):
    with open(os.path.join(snapshot, detect.SOURCE_MARKER), "w", encoding="utf-8") as handle:
        handle.write(f"{repo}\n{sha}\n")


def _make_pin(tmp, repo, sha):
    snapshot = os.path.join(tmp, "snapshot")
    target = os.path.join(snapshot, "diu-stop")
    os.makedirs(target)
    _write_marker(snapshot, repo, sha)
    link = os.path.join(tmp, "link")
    os.symlink(target, link)
    return link, snapshot


def _load_hook_health_detect():
    path = os.path.normpath(os.path.join(HOOK_DIR, "..", "hook-health", "detect.py"))
    spec = importlib.util.spec_from_file_location("hook_health_detect_for_reinstall_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def empty_settings(_path):
    return {"hooks": {}}


def fake_git(branch="main", behind="0", fail=(), record=None):
    def run(args, cwd, timeout=None):
        if record is not None:
            record.append(args)
        key = args[0]
        if key in fail:
            return None
        if key == "branch":
            return branch
        if key == "rev-list":
            return behind
        if key == "fetch":
            return ""
        return ""
    return run


class TestAdvisoryFires(unittest.TestCase):
    def test_hit_feature_branch_far_behind_trunk(self):
        line = detect.advisory("/repo/catstack", "feat/skill-usage-log", 40)
        self.assertIsNotNone(line)
        self.assertIn("feat/skill-usage-log", line)
        self.assertIn("40 commits behind origin/main", line)
        self.assertIn("install.sh", line)

    def test_hit_on_main_but_one_commit_behind(self):
        line = detect.advisory("/repo/catstack", "main", 1)
        self.assertIsNotNone(line)
        self.assertIn("1 commit behind", line)

    def test_hit_decide_returns_context_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            env = {"CATSTACK_HOOKS_REPO": repo, "HOOK_FRESHNESS_STATE_DIR": tmp}
            with patch.object(detect, "STATE_DIR", tmp):
                out = detect.decide_json(
                    {"transcript_path": os.path.join(tmp, "t.jsonl")},
                    env=env,
                    run=fake_git(branch="feat/x", behind="3"),
                    settings_path=os.path.join(tmp, "settings.json"),
                    load=empty_settings,
                )
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("3 commits behind", payload["hookSpecificOutput"]["additionalContext"])

    def test_hit_prints_once_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            env = {"CATSTACK_HOOKS_REPO": repo}
            payload = {"transcript_path": os.path.join(tmp, "t.jsonl")}
            with patch.object(detect, "STATE_DIR", tmp):
                first = detect.decide(
                    payload,
                    env=env,
                    run=fake_git(branch="feat/x", behind="3"),
                    settings_path=os.path.join(tmp, "settings.json"),
                    load=empty_settings,
                )
                second = detect.decide(
                    payload,
                    env=env,
                    run=fake_git(branch="feat/x", behind="3"),
                    settings_path=os.path.join(tmp, "settings.json"),
                    load=empty_settings,
                )
        self.assertIsNotNone(first)
        self.assertIsNone(second)


class TestAdvisorySilent(unittest.TestCase):
    def test_no_hit_on_main_up_to_date(self):
        self.assertIsNone(detect.advisory("/repo/catstack", "main", 0))

    def test_no_hit_when_behind_count_unavailable(self):
        self.assertIsNone(detect.advisory("/repo/catstack", "main", None))

    def test_an_unresolvable_override_is_reported_unchecked_not_silent(self):
        out = detect.decide(
            {},
            env={"CATSTACK_HOOKS_REPO": "/nope/not/a/repo"},
            state=False,
            settings_path="/tmp/settings.json",
            load=empty_settings,
        )
        self.assertIn("unchecked, not clean", out)
        self.assertIn("/nope/not/a/repo", out)

    def test_missing_settings_file_reports_unchecked_through_decide(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = detect.decide(
                {},
                env={"CATSTACK_HOOKS_REPO": "/nope/not/a/repo"},
                state=False,
                settings_path=os.path.join(tmp, ".claude", "settings.json"),
            )
        self.assertIn("could not check", line)
        self.assertIn("does not exist", line)

    def test_no_hit_when_disabled_by_env(self):
        self.assertIsNone(detect.decide({}, env={"CATSTACK_HOOK_FRESHNESS": "0"}))

    def test_no_hit_when_set_to_off(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"command": "python3 /nope/missing.py"}]}]}}

        def run(value):
            env = {"CATSTACK_HOOKS_REPO": "/nope/not/a/repo"}
            if value is not None:
                env["CATSTACK_HOOK_FRESHNESS"] = value
            return detect.decide({}, env=env, state=False, load=lambda _p: settings)

        self.assertIsNotNone(run(None))
        self.assertIsNone(run("off"))

    def test_mode_values(self):
        self.assertEqual(detect.freshness_mode({}), ("local", None))
        self.assertEqual(detect.freshness_mode({"CATSTACK_HOOK_FRESHNESS": " Fetch "}), ("fetch", None))
        self.assertEqual(detect.freshness_mode({"CATSTACK_HOOK_FRESHNESS": "local"}), ("local", None))
        self.assertEqual(detect.freshness_mode({"CATSTACK_HOOK_FRESHNESS": "false"})[0], "off")
        mode, note = detect.freshness_mode({"CATSTACK_HOOK_FRESHNESS": "sometimes"})
        self.assertEqual(mode, "local")
        self.assertIn("CATSTACK_HOOK_FRESHNESS=sometimes", note)

    def test_retired_fetch_flag_is_named_and_ignored(self):
        mode, note = detect.freshness_mode({"CATSTACK_HOOK_FRESHNESS_FETCH": "1"})
        self.assertEqual(mode, "local")
        self.assertIn("CATSTACK_HOOK_FRESHNESS_FETCH is retired", note)
        with tempfile.TemporaryDirectory() as tmp:
            line = detect.decide(
                {},
                env={"CATSTACK_HOOKS_REPO": "/nope/not/a/repo", "CATSTACK_HOOK_FRESHNESS_FETCH": "1"},
                state=False,
                settings_path=os.path.join(tmp, "settings.json"),
                load=lambda _p: {"hooks": {}},
            )
        self.assertIn("CATSTACK_HOOK_FRESHNESS_FETCH is retired", line)

    def test_fails_open_when_git_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            branch, behind = detect.repo_state(repo, env={}, run=fake_git(fail=("rev-list",)))
        self.assertIsNone(behind)

    def test_no_fetch_unless_opted_in(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            detect.repo_state(repo, env={}, run=fake_git(record=calls))
        self.assertNotIn("fetch", [c[0] for c in calls])

    def test_retired_fetch_flag_does_not_fetch(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            detect.repo_state(repo, env={"CATSTACK_HOOK_FRESHNESS_FETCH": "1"}, run=fake_git(record=calls))
        self.assertNotIn("fetch", [c[0] for c in calls])

    def test_fetch_when_opted_in(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            detect.repo_state(repo, env={"CATSTACK_HOOK_FRESHNESS": "fetch"}, run=fake_git(record=calls))
        self.assertIn("fetch", [c[0] for c in calls])

    def test_fails_open_on_garbage_stdin(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(out):
                claude_prompt_submit.main()
        self.assertEqual(out.getvalue(), "")


class TestRepoResolution(unittest.TestCase):
    def _pinned_link(self, tmp, repo, sha):
        snapshot = os.path.join(tmp, "snapshot")
        target = os.path.join(snapshot, "diu-stop")
        os.makedirs(target)
        with open(os.path.join(snapshot, detect.SOURCE_MARKER), "w", encoding="utf-8") as handle:
            handle.write(f"{repo}\n{sha}\n")
        link = os.path.join(tmp, "link")
        os.symlink(target, link)
        return link

    def test_hit_resolves_repo_and_pinned_sha_from_source_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            link = self._pinned_link(tmp, repo, "abc123")
            with patch.object(detect, "ANCHOR_LINK", link):
                self.assertEqual(detect.resolve_repo(env={}), repo)
                self.assertEqual(detect.resolve_pinned_sha(env={}), "abc123")

    def test_no_hit_when_source_marker_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = os.path.join(tmp, "snapshot")
            target = os.path.join(snapshot, "diu-stop")
            os.makedirs(target)
            link = os.path.join(tmp, "link")
            os.symlink(target, link)
            with patch.object(detect, "ANCHOR_LINK", link):
                self.assertIsNone(detect.resolve_repo(env={}))
                self.assertIsNone(detect.resolve_pinned_sha(env={}))

    def test_override_env_wins_over_source_marker_and_has_no_pinned_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            override = os.path.join(tmp, "override-repo")
            os.makedirs(os.path.join(override, ".git"))
            link = self._pinned_link(tmp, repo, "abc123")
            with patch.object(detect, "ANCHOR_LINK", link):
                env = {"CATSTACK_HOOKS_REPO": override}
                self.assertEqual(detect.resolve_repo(env=env), override)
                self.assertIsNone(detect.resolve_pinned_sha(env=env))

    def test_advisory_measures_the_pinned_sha_not_the_live_checkouts_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            link = self._pinned_link(tmp, repo, "old-sha")
            with patch.object(detect, "ANCHOR_LINK", link):
                resolved_repo = detect.resolve_repo(env={})
                pinned = detect.resolve_pinned_sha(env={})
                calls = []

                def run(args, cwd, timeout=None):
                    calls.append(args)
                    if args[0] == "branch":
                        return "main"
                    if args[0] == "rev-list":
                        return "12"
                    return ""

                branch, behind = detect.repo_state(resolved_repo, env={}, run=run, ref=pinned or "HEAD")
            rev_list_call = next(c for c in calls if c[0] == "rev-list")
            self.assertEqual(rev_list_call[-1], f"old-sha..{detect.TRUNK}")
            self.assertEqual(behind, 12)
            self.assertIn("12 commits behind", detect.advisory(resolved_repo, branch, behind))

    def test_decide_resolves_through_source_marker_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            os.makedirs(os.path.join(repo, ".git"))
            link = self._pinned_link(tmp, repo, "old-sha")
            with patch.object(detect, "ANCHOR_LINK", link), patch.object(detect, "STATE_DIR", tmp):
                out = detect.decide(
                    {"transcript_path": os.path.join(tmp, "t.jsonl")},
                    env={},
                    run=fake_git(branch="main", behind="7"),
                    settings_path=os.path.join(tmp, "settings.json"),
                    load=empty_settings,
                )
        self.assertIn("7 commits behind", out)


class TestUnresolvableHookSweep(unittest.TestCase):
    """A registered hook whose script path is gone is unchecked, never clean.

    Mirrors the real failure: ~/.claude/hooks/split-scope pointed into a deleted
    worktree, so the gate could not run for a whole session and said nothing.
    """

    def _settings(self, commands):
        return {"hooks": {"UserPromptSubmit": [{"matcher": "*", "hooks": [
            {"type": "command", "command": c} for c in commands
        ]}]}}

    def test_names_a_registered_hook_whose_script_is_missing(self):
        settings = self._settings([
            "python3 /real/hooks/diu-stop/claude_stop_check.py",
            "python3 /gone/hooks/split-scope/claude_prompt_submit.py",
        ])
        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json",
            load=lambda _p: settings,
            exists=lambda p: p.startswith("/real/"),
        )
        self.assertIsNone(unreadable)
        self.assertEqual(missing, ["/gone/hooks/split-scope/claude_prompt_submit.py"])
        line = detect.unresolvable_advisory(missing, unreadable)
        self.assertIn("split-scope", line)
        self.assertIn("unchecked, not clean", line)

    def test_silent_when_every_registered_hook_resolves(self):
        settings = self._settings(["python3 /real/hooks/diu-stop/claude_stop_check.py"])
        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json",
            load=lambda _p: settings,
            exists=lambda _p: True,
        )
        self.assertEqual((missing, unreadable), ([], None))
        self.assertIsNone(detect.unresolvable_advisory(missing, unreadable))

    def test_an_unreadable_settings_file_reports_unchecked_not_clean(self):
        def boom(_path):
            raise ValueError("Expecting ',' delimiter: line 4 column 3")

        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json", load=boom, exists=lambda _p: True,
        )
        self.assertEqual(missing, [])
        self.assertIsNotNone(unreadable)
        line = detect.unresolvable_advisory(missing, unreadable)
        self.assertIn("could not check", line)
        self.assertIn("unchecked rather than healthy", line)

    def test_a_missing_settings_file_reports_unchecked_not_clean(self):
        def gone(_path):
            raise FileNotFoundError(2, "No such file or directory")

        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json", load=gone, exists=lambda _p: True,
        )
        self.assertEqual(missing, [])
        self.assertIn("does not exist", unreadable)

    def test_unexpanded_variables_are_not_reported_as_missing(self):
        settings = self._settings(["python3 $UNSET_ROOT/hooks/x/run.py"])
        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json",
            load=lambda _p: settings,
            exists=lambda _p: False,
        )
        self.assertEqual((missing, unreadable), ([], None))

    def test_a_runner_script_resolves_against_the_runners_hooks_root_not_the_cwd(self):
        settings = self._settings([
            "python3 /home/u/.claude/hooks/_runner/run.py --timeout 9.5 diu-stop/claude_stop_check.py",
        ])
        checked = []

        def exists(path):
            checked.append(path)
            return path.startswith("/home/u/.claude/hooks/")

        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json", load=lambda _p: settings, exists=exists,
        )
        self.assertEqual((missing, unreadable), ([], None))
        self.assertIn("/home/u/.claude/hooks/diu-stop/claude_stop_check.py", checked)

    def test_a_missing_runner_script_is_named_by_its_full_path(self):
        settings = self._settings([
            "python3 /home/u/.claude/hooks/_runner/run.py --timeout 9.5 split-scope/claude_prompt_submit.py",
        ])
        missing, unreadable = detect.unresolvable_hooks(
            settings_path="/tmp/settings.json",
            load=lambda _p: settings,
            exists=lambda p: p == "/home/u/.claude/hooks/_runner/run.py",
        )
        self.assertIsNone(unreadable)
        self.assertEqual(missing, ["/home/u/.claude/hooks/split-scope/claude_prompt_submit.py"])


class TestAutoReinstallTrigger(unittest.TestCase):
    """Real temp git repos: a merge on the tracked base branch that touches a
    hook or skill directory should trigger exactly one reinstall."""

    def _build_repo(self, tmp):
        repo = os.path.join(tmp, "repo")
        init_repo(repo, "-b", "main", env=GIT_ENV)
        os.makedirs(os.path.join(repo, "engine", "hooks"))
        with open(os.path.join(repo, "engine", "hooks", "placeholder.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")
        with open(os.path.join(repo, "install.sh"), "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(repo, "install.sh"), 0o755)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "baseline")
        sha_a = _git(repo, "rev-parse", "HEAD").stdout.strip()
        return repo, sha_a

    def _add_hook_change(self, repo):
        with open(os.path.join(repo, "engine", "hooks", "new-hook.py"), "w", encoding="utf-8") as handle:
            handle.write("y = 2\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add hook")
        return _git(repo, "rev-parse", "HEAD").stdout.strip()

    def test_hit_triggers_reinstall_when_main_branch_gains_a_hook_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            self._add_hook_change(repo)
            link, _snapshot = _make_pin(tmp, repo, sha_a)
            calls = []
            with patch.object(detect, "ANCHOR_LINK", link):
                result = detect.maybe_reinstall({}, env={}, spawn=lambda r: calls.append(r) or True)
        self.assertTrue(result)
        self.assertEqual(calls, [repo])

    def test_no_hit_feature_branch_gaining_a_hook_change_triggers_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            _git(repo, "checkout", "-q", "-b", "feature/x")
            self._add_hook_change(repo)
            link, _snapshot = _make_pin(tmp, repo, sha_a)
            calls = []
            with patch.object(detect, "ANCHOR_LINK", link):
                result = detect.maybe_reinstall({}, env={}, spawn=lambda r: calls.append(r) or True)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_no_hit_a_diff_that_never_touches_a_hook_or_skill_dir_triggers_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("docs only\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "docs")
            link, _snapshot = _make_pin(tmp, repo, sha_a)
            calls = []
            with patch.object(detect, "ANCHOR_LINK", link):
                result = detect.maybe_reinstall({}, env={}, spawn=lambda r: calls.append(r) or True)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_no_hit_a_second_trigger_with_no_new_commits_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            sha_b = self._add_hook_change(repo)
            link, snapshot = _make_pin(tmp, repo, sha_a)
            calls = []
            with patch.object(detect, "ANCHOR_LINK", link):
                first = detect.maybe_reinstall({}, env={}, spawn=lambda r: calls.append(r) or True)
                _write_marker(snapshot, repo, sha_b)
                second = detect.maybe_reinstall({}, env={}, spawn=lambda r: calls.append(r) or True)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(calls, [repo])


class TestReinstallLock(unittest.TestCase):
    def test_hit_second_claim_is_denied_while_the_first_lock_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "reinstall.lock")
            self.assertTrue(detect.claim_reinstall_lock(lock))
            self.assertFalse(detect.claim_reinstall_lock(lock))
            detect.release_reinstall_lock(lock)
            self.assertTrue(detect.claim_reinstall_lock(lock))

    def test_no_hit_a_stale_lock_is_reclaimed_instead_of_blocking_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "reinstall.lock")
            self.assertTrue(detect.claim_reinstall_lock(lock))
            old = time.time() - 1000
            os.utime(lock, (old, old))
            self.assertTrue(detect.claim_reinstall_lock(lock, stale_seconds=300))


class TestSpawnReinstall(unittest.TestCase):
    def test_hit_spawn_claims_the_lock_and_launches_a_detached_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "reinstall.lock")
            calls = []

            def fake_popen(args, **kwargs):
                calls.append((args, kwargs))
                return Mock()

            result = detect.spawn_reinstall("/some/repo", popen=fake_popen, python="python3", lock_path=lock)
        self.assertTrue(result)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], "python3")
        self.assertEqual(args[2], "reinstall")
        self.assertEqual(args[3], "/some/repo")
        self.assertTrue(kwargs.get("start_new_session"))

    def test_no_hit_a_second_spawn_is_skipped_while_the_first_is_still_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "reinstall.lock")
            calls = []

            def fake_popen(args, **kwargs):
                calls.append(args)
                return Mock()

            first = detect.spawn_reinstall("/some/repo", popen=fake_popen, python="python3", lock_path=lock)
            second = detect.spawn_reinstall("/some/repo", popen=fake_popen, python="python3", lock_path=lock)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(calls), 1)


class TestRunReinstall(unittest.TestCase):
    """run_reinstall drives a real install.sh subprocess to completion and
    logs the outcome, so a failure is picked up by hook-health's own scan --
    the same path that already surfaces every other hook crash."""

    def _write_install_script(self, repo, body):
        os.makedirs(repo, exist_ok=True)
        path = os.path.join(repo, "install.sh")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(path, 0o755)
        return path

    def test_hit_a_failing_install_writes_a_crashed_row_hook_health_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._write_install_script(repo, "#!/bin/sh\necho boom 1>&2\nexit 1\n")
            metrics_path = os.path.join(tmp, "runs.jsonl")
            lock = os.path.join(tmp, "reinstall.lock")
            open(lock, "w", encoding="utf-8").close()

            detect.run_reinstall(repo, lock, metrics_path=metrics_path)

            self.assertFalse(os.path.exists(lock))
            with open(metrics_path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["harness"], "claude")
        self.assertEqual(row["hook"], "hook-freshness")
        self.assertEqual(row["script"], "install.sh")
        self.assertEqual(row["outcome"], "crashed")
        self.assertEqual(row["exit_code"], 1)
        self.assertIn("boom", row["stderr_tail"])
        hook_health = _load_hook_health_detect()
        self.assertEqual(len(hook_health.failures(rows, "claude")), 1)
        self.assertIn("hook-freshness/install.sh", hook_health.notice(rows, "claude"))

    def test_no_hit_a_successful_install_writes_a_row_hook_health_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._write_install_script(repo, "#!/bin/sh\necho all good\nexit 0\n")
            metrics_path = os.path.join(tmp, "runs.jsonl")
            lock = os.path.join(tmp, "reinstall.lock")
            open(lock, "w", encoding="utf-8").close()

            detect.run_reinstall(repo, lock, metrics_path=metrics_path)

            self.assertFalse(os.path.exists(lock))
            with open(metrics_path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "spoke")
        hook_health = _load_hook_health_detect()
        self.assertIsNone(hook_health.notice(rows, "claude"))


def _snapshot(tmp, repo, marker_lines, hooks=("diu-stop",)):
    snapshot = os.path.join(tmp, "snapshots", "v1")
    for name in hooks:
        os.makedirs(os.path.join(snapshot, name), exist_ok=True)
    if marker_lines is not None:
        with open(os.path.join(snapshot, detect.SOURCE_MARKER), "w", encoding="utf-8") as handle:
            handle.write("\n".join(marker_lines) + "\n")
    link = os.path.join(tmp, "anchor")
    os.symlink(os.path.join(snapshot, "diu-stop"), link)
    return snapshot, link


def _registered(tmp, name):
    script = os.path.join(tmp, "installed", "hooks", name, "claude_prompt_submit.py")
    os.makedirs(os.path.dirname(script), exist_ok=True)
    with open(script, "w", encoding="utf-8") as handle:
        handle.write("# registered\n")

    def load(_path):
        return {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": f"python3 {script}"}]}]}}
    return load


def _checkout(tmp, hooks=()):
    repo = os.path.join(tmp, "catstack")
    os.makedirs(os.path.join(repo, ".git"))
    for name in hooks:
        os.makedirs(os.path.join(repo, "engine", "hooks", name))
    return repo


class TestInstalledSourceRecord(unittest.TestCase):
    """The installed hooks run from a snapshot; judge them by what was installed."""

    def _decide(self, tmp, link, run, load=empty_settings):
        with patch.object(detect, "ANCHOR_LINK", link):
            return detect.decide(
                {}, env={}, run=run, state=False,
                settings_path=os.path.join(tmp, "settings.json"), load=load,
            )

    def test_branch_is_the_installed_ref_not_the_checkouts_current_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _checkout(tmp)
            _snapshot(tmp, repo, [repo, "abc123", "main"])
            calls = []
            out = self._decide(tmp, os.path.join(tmp, "anchor"), fake_git(branch="feature-x", behind="0", record=calls))
            self.assertIsNone(out)
            self.assertNotIn(["branch", "--show-current"], calls)

    def test_an_install_taken_from_a_feature_branch_names_that_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _checkout(tmp)
            _snapshot(tmp, repo, [repo, "abc123", "feature-y"])
            out = self._decide(tmp, os.path.join(tmp, "anchor"), fake_git(branch="main", behind="0"))
            self.assertIn("on branch `feature-y`", out)

    def test_a_registered_hook_missing_from_the_snapshot_is_deleted_even_if_the_checkout_has_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _checkout(tmp, hooks=("split-scope",))
            _snapshot(tmp, repo, [repo, "abc123", "main"])
            findings = self._findings(tmp, _registered(tmp, "split-scope"))
            rules = [f.rule_id for f in findings]
            self.assertIn(detect.RULE_DELETED_INSTALLED_HOOK, rules)

    def test_a_registered_hook_present_in_the_snapshot_is_not_deleted_even_if_the_checkout_lost_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _checkout(tmp)
            _snapshot(tmp, repo, [repo, "abc123", "main"], hooks=("diu-stop", "split-scope"))
            findings = self._findings(tmp, _registered(tmp, "split-scope"))
            self.assertNotIn(detect.RULE_DELETED_INSTALLED_HOOK, [f.rule_id for f in findings])

    def _findings(self, tmp, load):
        with patch.object(detect, "ANCHOR_LINK", os.path.join(tmp, "anchor")):
            return detect._findings(
                {}, env={}, run=fake_git(branch="main", behind="0"), state=False,
                settings_path=os.path.join(tmp, "settings.json"), load=load,
            )

    def test_a_missing_source_record_is_reported_unchecked_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _snapshot(tmp, None, None)
            out = self._decide(tmp, os.path.join(tmp, "anchor"), fake_git(branch="main", behind="0"))
            self.assertIsNotNone(out)
            self.assertIn("unchecked, not clean", out)
            self.assertIn(detect.SOURCE_MARKER, out)

    def test_an_unknown_pinned_commit_is_reported_unchecked(self):
        for recorded in ("unknown", ""):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as tmp:
                repo = _checkout(tmp)
                _snapshot(tmp, repo, [repo, recorded, "main"])
                calls = []
                out = self._decide(tmp, os.path.join(tmp, "anchor"), fake_git(behind="0", record=calls))
                self.assertIn("does not record the commit", out)
                self.assertFalse([c for c in calls if c[0] == "rev-list"])

    def test_a_legacy_link_straight_into_a_checkout_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _checkout(tmp, hooks=("diu-stop",))
            link = os.path.join(tmp, "anchor")
            os.symlink(os.path.join(repo, "engine", "hooks", "diu-stop"), link)
            with patch.object(detect, "ANCHOR_LINK", link):
                self.assertEqual(detect.resolve_repo(env={}), os.path.realpath(repo))
            out = self._decide(tmp, link, fake_git(branch="main", behind="3"))
            self.assertIn("3 commits behind", out)


class TestReinstallReviewFixes(TestAutoReinstallTrigger):
    """Follow-ups from the auto-reinstall review: never reinstall uncommitted work, never
    tell the agent to run install.sh while one is already running, bound and
    log the worker, remember failed commits, and skip git on the no-op path."""

    def _trigger(self, tmp, repo, pinned, run=None, spawn=None):
        link, _snapshot = _make_pin(tmp, repo, pinned)
        calls = []
        kwargs = {"env": {}, "spawn": spawn or (lambda r: calls.append(r) or True)}
        if run is not None:
            kwargs["run"] = run
        with patch.object(detect, "ANCHOR_LINK", link), patch.object(detect, "STATE_DIR", os.path.join(tmp, "state")):
            result = detect.maybe_reinstall({}, **kwargs)
        return result, calls

    def test_a_checkout_with_uncommitted_changes_is_not_auto_reinstalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            self._add_hook_change(repo)
            with open(os.path.join(repo, "engine", "hooks", "wip.py"), "w", encoding="utf-8") as handle:
                handle.write("half done\n")
            result, calls = self._trigger(tmp, repo, sha_a)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_a_clean_checkout_still_reinstalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            self._add_hook_change(repo)
            result, calls = self._trigger(tmp, repo, sha_a)
        self.assertTrue(result)
        self.assertEqual(calls, [repo])

    def test_the_no_op_path_starts_no_git_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            ran = []

            def run(args, cwd, timeout=None):
                ran.append(args)
                return None
            result, calls = self._trigger(tmp, repo, sha_a, run=run)
        self.assertFalse(result)
        self.assertEqual(ran, [])

    def test_a_commit_whose_reinstall_failed_is_not_retried_every_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            sha_b = self._add_hook_change(repo)
            with open(os.path.join(repo, "install.sh"), "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\necho boom 1>&2\nexit 1\n")
            _git(repo, "commit", "-qam", "break install")
            sha_c = _git(repo, "rev-parse", "HEAD").stdout.strip()
            state = os.path.join(tmp, "state")
            lock = os.path.join(state, "reinstall.lock")
            os.makedirs(state)
            open(lock, "w", encoding="utf-8").close()
            with patch.object(detect, "STATE_DIR", state):
                detect.run_reinstall(repo, lock, metrics_path=os.path.join(tmp, "runs.jsonl"))
            result, calls = self._trigger(tmp, repo, sha_a)
        self.assertNotEqual(sha_b, sha_c)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_the_worker_has_a_time_limit_and_a_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = {}

            class SlowProc:
                returncode = None

                def communicate(self, timeout=None):
                    if "timeout" not in seen:
                        seen["timeout"] = timeout
                        raise subprocess.TimeoutExpired(["bash"], timeout)
                    return b"", b"killed"

                def kill(self):
                    seen["killed"] = True
                    self.returncode = -9

            lock = os.path.join(tmp, "reinstall.lock")
            open(lock, "w", encoding="utf-8").close()
            metrics = os.path.join(tmp, "runs.jsonl")
            with patch.object(detect, "STATE_DIR", tmp):
                detect.run_reinstall(os.path.join(tmp, "repo"), lock, metrics_path=metrics, popen=lambda *a, **k: SlowProc())
            with open(metrics, encoding="utf-8") as handle:
                row = json.loads(handle.readline())
        self.assertIsNotNone(seen["timeout"])
        self.assertLess(seen["timeout"], detect.REINSTALL_LOCK_STALE_SECONDS)
        self.assertTrue(seen.get("killed"))
        self.assertEqual(row["outcome"], "timed_out")
        self.assertFalse(os.path.exists(lock))

    def test_the_worker_stderr_goes_to_a_log_not_devnull(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, "reinstall.lock")
            seen = {}

            def fake_popen(args, **kwargs):
                seen.update(kwargs)
                return Mock()
            detect.spawn_reinstall("/some/repo", popen=fake_popen, python="python3", lock_path=lock)
            log_name = getattr(seen.get("stderr"), "name", "")
        self.assertIsNot(seen.get("stderr"), subprocess.DEVNULL)
        self.assertEqual(os.path.basename(log_name), "reinstall-worker.log")

    def test_a_started_reinstall_replaces_the_run_install_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sha_a = self._build_repo(tmp)
            link, _snapshot = _make_pin(tmp, repo, sha_a)
            with patch.object(detect, "ANCHOR_LINK", link):
                findings = detect._findings(
                    {"_reinstall_started": True}, env={}, run=fake_git(branch="main", behind="4"),
                    state=False, settings_path=os.path.join(tmp, "settings.json"), load=empty_settings,
                )
        stale = [f for f in findings if f.rule_id == detect.RULE_STALE_CHECKOUT]
        self.assertEqual(len(stale), 1)
        self.assertNotIn("install.sh`", stale[0].message)
        self.assertIn("reinstall", stale[0].message)


if __name__ == "__main__":
    unittest.main()
