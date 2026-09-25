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
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "test"))

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402
from git_test_repo import init_repo  # noqa: E402


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


def fake_reinstall_git(branch="main", head="new-sha", diff_paths=(), fail=()):
    def run(args, cwd, timeout=None):
        key = args[0]
        if key in fail:
            return None
        if key == "branch":
            return branch
        if key == "rev-parse":
            return head
        if key == "diff":
            return "\n".join(diff_paths)
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

    def test_no_hit_when_repo_unresolvable(self):
        self.assertIsNone(
            detect.decide(
                {},
                env={"CATSTACK_HOOKS_REPO": "/nope/not/a/repo"},
                settings_path="/tmp/settings.json",
                load=empty_settings,
            )
        )

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


class TestAutoReinstallTrigger(unittest.TestCase):
    """Whether hook-freshness should fire the auto-reinstall run. Mirrors the
    real failure: the checkout pulls a hook fix on main and nothing installs
    it until a person remembers to rerun install.sh."""

    def test_hit_fires_when_main_moves_onto_hook_paths(self):
        run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("engine/hooks/foo/detect.py",))
        head, reason = detect.reinstall_target("/repo/catstack", "old-sha", run=run)
        self.assertEqual(head, "new-sha")
        self.assertEqual(reason, "trigger")

    def test_hit_fires_on_a_skills_path_too(self):
        run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("corpus/skills/foo/SKILL.md",))
        head, _reason = detect.reinstall_target("/repo/catstack", "old-sha", run=run)
        self.assertEqual(head, "new-sha")

    def test_no_hit_on_feature_branch(self):
        run = fake_reinstall_git(branch="feat/x", head="new-sha", diff_paths=("engine/hooks/foo/detect.py",))
        head, reason = detect.reinstall_target("/repo/catstack", "old-sha", run=run)
        self.assertIsNone(head)
        self.assertEqual(reason, "not-base-branch")

    def test_no_hit_when_already_up_to_date(self):
        run = fake_reinstall_git(branch="main", head="same-sha")
        head, reason = detect.reinstall_target("/repo/catstack", "same-sha", run=run)
        self.assertIsNone(head)
        self.assertEqual(reason, "up-to-date")

    def test_no_hit_when_diff_does_not_touch_reinstall_paths(self):
        run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("README.md",))
        head, reason = detect.reinstall_target("/repo/catstack", "old-sha", run=run)
        self.assertIsNone(head)
        self.assertEqual(reason, "no-reinstall-paths")

    def test_no_hit_when_there_is_no_pinned_baseline(self):
        run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("engine/hooks/foo/detect.py",))
        head, reason = detect.reinstall_target("/repo/catstack", None, run=run)
        self.assertIsNone(head)
        self.assertEqual(reason, "no-baseline")

    def test_hit_trigger_spawns_and_claims_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            spawned = []
            run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("engine/hooks/foo/detect.py",))
            with patch.object(detect, "STATE_DIR", tmp):
                reason = detect.trigger_auto_reinstall(
                    "/repo/catstack", "old-sha", harness="claude", session_id="s1", run=run,
                    spawn=lambda *args: spawned.append(args),
                )
                lock_exists_during_call = spawned[0][3]
            self.assertEqual(reason, "triggered")
            self.assertEqual(len(spawned), 1)
            self.assertTrue(os.path.isfile(lock_exists_during_call))

    def test_no_hit_trigger_skips_when_already_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            spawned = []
            run = fake_reinstall_git(branch="main", head="new-sha", diff_paths=("engine/hooks/foo/detect.py",))
            with patch.object(detect, "STATE_DIR", tmp):
                detect._claim_reinstall_lock("/repo/catstack")
                reason = detect.trigger_auto_reinstall(
                    "/repo/catstack", "old-sha", harness="claude", session_id="s1", run=run,
                    spawn=lambda *args: spawned.append(args),
                )
            self.assertEqual(reason, "locked")
            self.assertEqual(spawned, [])


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _load_hook_health_notice():
    path = os.path.join(REPO_ROOT, "engine", "hooks", "hook-health", "detect.py")
    spec = importlib.util.spec_from_file_location("hook_health_detect_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.notice


class TestAutoReinstallIntegration(unittest.TestCase):
    """End-to-end: a real temp git repo, a real background subprocess
    running a stub install.sh, and the real runs.jsonl row it writes."""

    def _git(self, repo, *args):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=GIT_ENV)

    def _head(self, repo):
        out = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"], check=True, capture_output=True, text=True, env=GIT_ENV,
        )
        return out.stdout.strip()

    def _build_repo(self, tmp, install_body, branch="main"):
        repo = os.path.join(tmp, "catstack")
        init_repo(repo, "-b", branch, env=GIT_ENV)
        install_path = os.path.join(repo, "install.sh")
        with open(install_path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(install_path, 0o755)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "init")
        pinned = self._head(repo)
        os.makedirs(os.path.join(repo, "engine", "hooks", "demo"), exist_ok=True)
        with open(os.path.join(repo, "engine", "hooks", "demo", "detect.py"), "w", encoding="utf-8") as handle:
            handle.write("pass\n")
        with open(install_path, "w", encoding="utf-8") as handle:
            handle.write(install_body)
        os.chmod(install_path, 0o755)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "add a hook and update install.sh")
        head = self._head(repo)
        return repo, pinned, head

    def _wait_for_rows(self, metrics_dir, count, timeout=10):
        path = os.path.join(metrics_dir, "runs.jsonl")
        deadline = time.monotonic() + timeout
        rows = []
        while time.monotonic() < deadline:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    rows = [json.loads(line) for line in handle if line.strip()]
                if len(rows) >= count:
                    return rows
            time.sleep(0.1)
        self.fail(f"timed out waiting for {count} row(s) in {path}, saw {len(rows)}")

    def test_hit_base_branch_merge_triggers_one_install_run_and_one_metrics_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, pinned, _head = self._build_repo(tmp, "#!/bin/sh\necho installed\nexit 0\n")
            metrics_dir = os.path.join(tmp, "metrics")
            with patch.object(detect, "STATE_DIR", os.path.join(tmp, "state")), \
                    patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir}):
                reason = detect.trigger_auto_reinstall(repo, pinned, harness="claude", session_id="s1")
                self.assertEqual(reason, "triggered")
                rows = self._wait_for_rows(metrics_dir, count=1)
                time.sleep(0.3)
                rows = self._wait_for_rows(metrics_dir, count=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hook"], "hook-freshness")
        self.assertEqual(rows[0]["script"], "auto-reinstall")
        self.assertEqual(rows[0]["exit_code"], 0)

    def test_no_hit_feature_branch_checkout_triggers_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, pinned, _head = self._build_repo(tmp, "#!/bin/sh\nexit 0\n", branch="feat/x")
            metrics_dir = os.path.join(tmp, "metrics")
            with patch.object(detect, "STATE_DIR", os.path.join(tmp, "state")), \
                    patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir}):
                reason = detect.trigger_auto_reinstall(repo, pinned, harness="claude", session_id="s1")
                time.sleep(0.5)
            self.assertEqual(reason, "not-base-branch")
            self.assertFalse(os.path.isfile(os.path.join(metrics_dir, "runs.jsonl")))

    def test_hit_a_failing_install_produces_a_failed_row_and_a_hook_health_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, pinned, _head = self._build_repo(tmp, "#!/bin/sh\necho boom >&2\nexit 1\n")
            metrics_dir = os.path.join(tmp, "metrics")
            with patch.object(detect, "STATE_DIR", os.path.join(tmp, "state")), \
                    patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir}):
                detect.trigger_auto_reinstall(repo, pinned, harness="claude", session_id="s1")
                rows = self._wait_for_rows(metrics_dir, count=1)
        self.assertEqual(rows[0]["outcome"], "crashed")
        self.assertEqual(rows[0]["exit_code"], 1)
        notice = _load_hook_health_notice()
        message = notice(rows, "claude")
        self.assertIsNotNone(message)
        self.assertIn("hook-freshness/auto-reinstall", message)

    def test_no_hit_second_trigger_with_no_new_commits_is_a_no_op(self):
        install_body = (
            "#!/bin/sh\n"
            "dir=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
            "printf '%s\\n' \"$(git -C \"$dir\" rev-parse HEAD)\" > \"$dir/.pinned-sha\"\n"
            "exit 0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo, pinned, head = self._build_repo(tmp, install_body)
            metrics_dir = os.path.join(tmp, "metrics")
            with patch.object(detect, "STATE_DIR", os.path.join(tmp, "state")), \
                    patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir}):
                first = detect.trigger_auto_reinstall(repo, pinned, harness="claude", session_id="s1")
                self.assertEqual(first, "triggered")
                self._wait_for_rows(metrics_dir, count=1)
                deadline = time.monotonic() + 10
                new_pinned = None
                marker = os.path.join(repo, ".pinned-sha")
                while time.monotonic() < deadline:
                    if os.path.isfile(marker):
                        with open(marker, encoding="utf-8") as handle:
                            new_pinned = handle.read().strip()
                        if new_pinned:
                            break
                    time.sleep(0.1)
                self.assertEqual(new_pinned, head)
                second = detect.trigger_auto_reinstall(repo, new_pinned, harness="claude", session_id="s1")
                time.sleep(0.5)
                rows = self._wait_for_rows(metrics_dir, count=1)
        self.assertEqual(second, "up-to-date")
        self.assertEqual(len(rows), 1)


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


if __name__ == "__main__":
    unittest.main()
