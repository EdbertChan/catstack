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
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402


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
    def test_hit_resolves_repo_from_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "catstack")
            target = os.path.join(repo, "engine", "hooks", "diu-stop")
            os.makedirs(target)
            os.makedirs(os.path.join(repo, ".git"))
            with patch.object(detect, "ANCHOR_LINK", os.path.join(tmp, "link")):
                os.symlink(target, os.path.join(tmp, "link"))
                self.assertEqual(detect.resolve_repo(env={}), os.path.realpath(repo))


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
