#!/usr/bin/env python3
"""Tests for the hook-freshness UserPromptSubmit hook.

Run: python3 -m unittest discover -s engine/hooks/hook-freshness/tests -v

Git is injected as a fake runner, so no test touches a real repo or the
network. The stale case mirrors the real failure: the checkout behind the
live symlinks on a feature branch, dozens of commits behind origin/main,
with merged hook fixes therefore not installed.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
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


def pinned_link(tmp, repo, sha):
    snapshot = os.path.join(tmp, "snapshot")
    target = os.path.join(snapshot, "diu-stop")
    os.makedirs(target)
    with open(os.path.join(snapshot, detect.SOURCE_MARKER), "w", encoding="utf-8") as handle:
        handle.write(f"{repo}\n{sha}\n")
    link = os.path.join(tmp, "link")
    os.symlink(target, link)
    return link


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


def fake_repo_git(branch="main", head="new-sha", behind="0", diff_paths=("engine/hooks/foo/detect.py",), record=None):
    def run(args, cwd, timeout=None):
        if record is not None:
            record.append(list(args))
        key = args[0]
        if key == "branch":
            return branch
        if key == "rev-parse":
            return head
        if key == "diff":
            return "\n".join(diff_paths)
        if key == "rev-list":
            return behind
        return ""
    return run


def fake_popen(returncode=0, stdout=b"", stderr=b"", record=None):
    def popen(args, cwd=None, capture_output=None, timeout=None, check=None):
        if record is not None:
            record.append((list(args), cwd))
        return subprocess.CompletedProcess(list(args), returncode, stdout=stdout, stderr=stderr)
    return popen


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
    """Base-branch merges that touch hooks or skills reinstall themselves.

    Mirrors the real gap: a merge lands on main, the checkout is pulled
    forward, and the user used to have to say 'run install.sh again'
    themselves. Git and install.sh are both injected, so no test shells out
    for real.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "catstack")
        os.makedirs(os.path.join(self.repo, ".git"))
        self.metrics_dir = os.path.join(self.tmp.name, "metrics")
        self.state_patch = patch.object(detect, "STATE_DIR", self.tmp.name)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.env_patch = patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": self.metrics_dir})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _rows(self):
        path = os.path.join(self.metrics_dir, "runs.jsonl")
        try:
            with open(path, encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        except FileNotFoundError:
            return []

    def test_hit_merge_on_base_branch_with_relevant_diff_runs_install_and_writes_one_row(self):
        calls = []
        popen = fake_popen(returncode=0, stdout=b"install output", stderr=b"", record=calls)
        finding = detect.maybe_auto_reinstall(
            {"session_id": "s1"}, self.repo, "old-sha",
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["bash", os.path.join(self.repo, "install.sh")])
        rows = self._rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["hook"], "hook-freshness")
        self.assertEqual(rows[0]["script"], "install.sh")
        self.assertEqual(rows[0]["exit_code"], 0)
        self.assertNotIn(rows[0]["outcome"], detect.AUTO_REINSTALL_FAILURE_OUTCOMES)

    def test_no_hit_on_feature_branch_checkout(self):
        calls = []
        popen = fake_popen(record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, "old-sha",
            env={}, run=fake_repo_git(branch="feat/x", head="new-sha"), popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(calls, [])
        self.assertEqual(self._rows(), [])

    def test_hit_failing_install_writes_failed_row_and_reports_finding(self):
        calls = []
        popen = fake_popen(returncode=1, stdout=b"", stderr=b"boom: something broke", record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, "old-sha",
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_id, detect.RULE_AUTO_REINSTALL_FAILED)
        self.assertIn("install.sh", finding.message)
        self.assertIn("boom: something broke", finding.message)
        self.assertEqual(len(calls), 1)
        rows = self._rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["exit_code"], 1)
        self.assertIn(rows[0]["outcome"], detect.AUTO_REINSTALL_FAILURE_OUTCOMES)

    def test_no_hit_second_trigger_with_no_new_commits_is_a_noop(self):
        calls = []
        popen = fake_popen(returncode=0, record=calls)
        first = detect.maybe_auto_reinstall(
            {}, self.repo, "old-sha",
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNone(first)
        self.assertEqual(len(calls), 1)

        second = detect.maybe_auto_reinstall(
            {}, self.repo, "new-sha",
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNone(second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self._rows()), 1)

    def test_no_hit_when_diff_has_no_relevant_paths(self):
        calls = []
        popen = fake_popen(record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, "old-sha",
            env={},
            run=fake_repo_git(branch="main", head="new-sha", diff_paths=("docs/readme.md",)),
            popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(calls, [])
        self.assertEqual(self._rows(), [])

    def test_no_hit_when_pinned_sha_missing(self):
        calls = []
        popen = fake_popen(record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, None,
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(calls, [])

    def test_no_hit_when_head_unchanged(self):
        calls = []
        popen = fake_popen(record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, "same-sha",
            env={}, run=fake_repo_git(branch="main", head="same-sha"), popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(calls, [])

    def test_no_hit_when_lock_already_held(self):
        lock_path = detect._auto_reinstall_lock_path()
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write("")
        calls = []
        popen = fake_popen(record=calls)
        finding = detect.maybe_auto_reinstall(
            {}, self.repo, "old-sha",
            env={}, run=fake_repo_git(branch="main", head="new-sha"), popen=popen,
        )
        self.assertIsNone(finding)
        self.assertEqual(calls, [])
        self.assertTrue(os.path.exists(lock_path))

    def test_hit_decide_reports_auto_reinstall_failure_end_to_end(self):
        link = pinned_link(self.tmp.name, self.repo, "old-sha")
        calls = []
        popen = fake_popen(returncode=1, stdout=b"", stderr=b"install exploded", record=calls)
        with patch.object(detect, "ANCHOR_LINK", link):
            out = detect.decide(
                {"transcript_path": os.path.join(self.tmp.name, "t.jsonl")},
                env={},
                run=fake_repo_git(branch="main", head="new-sha", behind="0"),
                popen=popen,
                settings_path=os.path.join(self.tmp.name, "settings.json"),
                load=empty_settings,
            )
        self.assertIsNotNone(out)
        self.assertIn("auto-reinstall failed", out)
        self.assertIn("install exploded", out)
        self.assertEqual(len(calls), 1)


class TestAutoReinstallRealGitDiff(unittest.TestCase):
    """The relevant-paths diff check against real git, not a fake runner."""

    def _env(self):
        return {
            **os.environ,
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }

    def _commit(self, repo, env, rel, contents):
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(contents + "\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", contents], check=True, capture_output=True, env=env)
        return subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"], check=True, capture_output=True, text=True, env=env,
        ).stdout.strip()

    def test_hit_real_git_diff_flags_a_hook_directory_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            env = self._env()
            init_repo(repo, "-b", "main", env=env)
            base = self._commit(repo, env, "README.md", "init")
            hook_change = self._commit(repo, env, "engine/hooks/foo/detect.py", "hook change")
            self.assertTrue(detect.diff_touches_relevant_paths(repo, base, hook_change))

    def test_no_hit_real_git_diff_ignores_an_unrelated_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            env = self._env()
            init_repo(repo, "-b", "main", env=env)
            base = self._commit(repo, env, "README.md", "init")
            docs_change = self._commit(repo, env, "docs/notes.md", "unrelated change")
            self.assertFalse(detect.diff_touches_relevant_paths(repo, base, docs_change))


if __name__ == "__main__":
    unittest.main()
