#!/usr/bin/env python3
"""Tests for auto-pr. Builds throwaway git repos for every scenario except
confirming repo_root() recognizes the real catstack checkout -- never
writes to the real checkout.

Run: python3 -m unittest discover -s hooks/auto-pr/tests -v
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(HOOK_DIR))
sys.path.insert(0, HOOK_DIR)

import claude_stop_autopr  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402
import install_codex_notify  # noqa: E402


def _git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True)


def make_repo(tmp: str) -> str:
    root = os.path.join(tmp, "repo")
    os.makedirs(root)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    os.makedirs(os.path.join(root, "engine", "hooks", "sample"), exist_ok=True)
    with open(os.path.join(root, "engine", "hooks", "sample", "detect.py"), "w", encoding="utf-8") as handle:
        handle.write("# placeholder\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_autopr.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def run_cursor(payload: dict, argv: list[str] | None = None) -> dict:
    out = io.StringIO()
    args = ["cursor_session.py", *(argv or [])]
    with patch.object(sys, "argv", args):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with redirect_stdout(out):
                cursor_session.main()
    return json.loads(out.getvalue() or "{}")


def run_codex(payload: dict, argv: list[str] | None = None) -> str:
    err = io.StringIO()
    args = ["codex_notify.py", *(argv or []), json.dumps(payload)]
    with patch.object(sys, "argv", args):
        with redirect_stderr(err):
            codex_notify.main()
    return err.getvalue()


class TestRepoScoping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_repo_root_does_not_match_outside_own_checkout(self):
        other = make_repo(self.tmp.name)
        self.assertIsNone(detect.repo_root({"cwd": other}))

    def test_repo_root_detects_the_real_catstack_checkout(self):
        self.assertEqual(detect.repo_root({"cwd": REPO_ROOT}), detect.OWN_REPO_ROOT)

    def test_repo_root_detects_a_linked_worktree_of_own_checkout(self):
        worktree = os.path.join(self.tmp.name, "linked-worktree")
        branch = "auto-pr-linked-worktree-test"
        _git(REPO_ROOT, "worktree", "add", "-q", "-b", branch, worktree, "HEAD")
        try:
            self.assertEqual(detect.repo_root({"cwd": worktree}), os.path.realpath(worktree))
        finally:
            _git(REPO_ROOT, "worktree", "remove", "--force", worktree)
            _git(REPO_ROOT, "branch", "-D", branch)


class TestRelevantPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_relevant_paths_changed_detects_hook_edit(self):
        with open(os.path.join(self.repo, "engine", "hooks", "sample", "detect.py"), "a", encoding="utf-8") as handle:
            handle.write("# edit\n")
        self.assertIn("engine/hooks/sample/detect.py", detect.relevant_paths_changed(self.repo))

    def test_relevant_paths_changed_ignores_unrelated_file(self):
        with open(os.path.join(self.repo, "unrelated.txt"), "w", encoding="utf-8") as handle:
            handle.write("hi\n")
        self.assertEqual(detect.relevant_paths_changed(self.repo), [])

    def test_clean_repo_with_no_relevant_changes_is_silent(self):
        self.assertIsNone(detect.decide({"cwd": self.repo}))


class TestDebounce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AUTO_PR_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name
        self.repo_tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.repo_tmp.name)
        with open(os.path.join(self.repo, "engine", "hooks", "sample", "detect.py"), "a", encoding="utf-8") as handle:
            handle.write("# edit\n")
        # decide() always scopes through repo_root(), which only matches the
        # real catstack checkout -- point it at this throwaway repo instead
        # so decide()'s debounce/deliver logic can be tested in isolation.
        patcher = patch.object(detect, "OWN_REPO_ROOT", os.path.realpath(self.repo))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()
        self.repo_tmp.cleanup()

    def test_debounce_defers_first_stop_then_fires_on_second_stable_stop(self):
        first = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNone(first)
        second = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNotNone(second)
        self.assertIn("catstack changes detected", second)

    def test_debounce_stays_silent_while_diff_keeps_changing(self):
        first = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNone(first)
        with open(os.path.join(self.repo, "engine", "hooks", "sample", "detect.py"), "a", encoding="utf-8") as handle:
            handle.write("# another edit\n")
        second = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNone(second)

    def test_already_prompted_blocks_repeat_delivery_for_same_hash(self):
        detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        delivered = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNotNone(delivered)
        third = detect.decide({"cwd": self.repo}, deliver=False, debounce=True)
        self.assertIsNone(third)

    def test_cursor_session_end_triggers_without_debounce(self):
        delivered = detect.decide({"cwd": self.repo}, deliver=True)
        self.assertIsNotNone(delivered)

    def test_cursor_mid_turn_stop_stays_silent_even_when_diff_stable(self):
        # deliver=None + no sessionEnd argv is exactly cursor_session.py's mid-turn call shape.
        first = detect.decide({"cwd": self.repo}, argv=[])
        second = detect.decide({"cwd": self.repo}, argv=[])
        self.assertIsNone(first)
        self.assertIsNone(second)


class TestHarnessWrappers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AUTO_PR_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name
        self.repo_tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.repo_tmp.name)
        with open(os.path.join(self.repo, "engine", "hooks", "sample", "detect.py"), "a", encoding="utf-8") as handle:
            handle.write("# edit\n")
        patcher = patch.object(detect, "OWN_REPO_ROOT", os.path.realpath(self.repo))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()
        self.repo_tmp.cleanup()

    def test_claude_stop_does_not_block_on_first_call(self):
        blocked, err = run_claude({"cwd": self.repo})
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_claude_stop_blocks_on_second_stable_call(self):
        run_claude({"cwd": self.repo})
        blocked, err = run_claude({"cwd": self.repo})
        self.assertTrue(blocked)
        self.assertIn("catstack changes detected", err)

    def test_claude_allows_clean_repo(self):
        clean_tmp = tempfile.TemporaryDirectory()
        try:
            clean_repo = make_repo(clean_tmp.name)
            with patch.object(detect, "OWN_REPO_ROOT", os.path.realpath(clean_repo)):
                blocked, err = run_claude({"cwd": clean_repo})
            self.assertFalse(blocked)
            self.assertEqual(err, "")
        finally:
            clean_tmp.cleanup()

    def test_cursor_stop_followup_is_empty(self):
        body = run_cursor({"cwd": self.repo})
        self.assertEqual(body.get("followup_message"), "")

    def test_cursor_session_end_followup_on_change(self):
        body = run_cursor({"cwd": self.repo}, argv=["sessionEnd"])
        self.assertIn("catstack changes detected", body.get("followup_message", ""))

    def test_codex_turn_complete_reports_relevant_change(self):
        message = run_codex({"type": "agent-turn-complete", "cwd": self.repo})
        self.assertIn("catstack changes detected", message)

    def test_codex_turn_complete_stays_silent_for_clean_repo(self):
        clean_tmp = tempfile.TemporaryDirectory()
        try:
            clean_repo = make_repo(clean_tmp.name)
            with patch.object(detect, "OWN_REPO_ROOT", os.path.realpath(clean_repo)):
                message = run_codex({"type": "agent-turn-complete", "cwd": clean_repo})
            self.assertEqual(message, "")
        finally:
            clean_tmp.cleanup()

    def test_malformed_stdin_fails_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stderr(err):
                claude_stop_autopr.main()
        self.assertEqual(err.getvalue(), "")


class TestGuardrails(unittest.TestCase):
    def test_stop_hook_active_skips(self):
        self.assertIsNone(detect.decide({"cwd": "/nonexistent", "stop_hook_active": True}))

    def test_detect_source_never_shells_out_to_git_write_verbs(self):
        # Requires the word to appear as its own quoted token (immediately
        # bounded by quote chars), so INSTRUCTION's prose ("...push to that
        # branch...") never trips this -- only an actual git-arg literal would.
        with open(os.path.join(HOOK_DIR, "detect.py"), encoding="utf-8") as handle:
            source = handle.read()
        forbidden = re.compile(
            r'["\'](?:commit|push|reset|checkout|rebase|merge|cherry-pick|stash|tag'
            r'|-b|-d|-D|--hard|--force)["\']'
        )
        matches = forbidden.findall(source)
        self.assertEqual(matches, [], f"detect.py must stay read-only git: found {matches}")


class TestCodexInstaller(unittest.TestCase):
    def test_compute_notify_update_prepends_and_chains(self):
        text = 'notify = ["python3", "/home/x/.codex/hooks/diu-stop/codex_notify.py"]\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(
            text, "/home/x/.codex/hooks/auto-pr/codex_notify.py"
        )
        self.assertTrue(changed)
        self.assertLess(new_text.index("auto-pr"), new_text.index("diu-stop"))


if __name__ == "__main__":
    unittest.main()
