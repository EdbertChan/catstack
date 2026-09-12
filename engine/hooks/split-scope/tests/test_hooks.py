#!/usr/bin/env python3
"""Unit tests for split-scope inject hooks."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_prompt_submit  # noqa: E402
import codex_prompt_submit  # noqa: E402
import cursor_before_submit  # noqa: E402
import cursor_post_tool_use  # noqa: E402
import detect  # noqa: E402
import state  # noqa: E402

SKILL_PATH = "/".join(("product", "skills", "split-scope", "SKILL.md"))
REMINDER = (
    "split-scope: this prompt plans multi-slice work. Before writing the plan "
    f"or PR stack, read the split-scope skill ({SKILL_PATH}, or the installed "
    "split-scope skill) and give each slice one review claim with a "
    "user-confirmed safety invariant."
)


def run_main(main, stdin_text: str) -> tuple[str, str, int]:
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with patch.object(sys, "stdin", io.StringIO(stdin_text)):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def run_json(main, payload: dict) -> tuple[str, str, int]:
    return run_main(main, json.dumps(payload))


class SplitScopeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        state.STATE_DIR = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestDetect(SplitScopeCase):
    def test_pr_stack_phrase_fires(self) -> None:
        self.assertTrue(detect.plans_multi_slice_work("Plan a PR stack for this change."))

    def test_split_this_into_phrase_fires(self) -> None:
        self.assertTrue(detect.plans_multi_slice_work("Split this into reviewable pieces."))

    def test_migration_plan_phrase_fires(self) -> None:
        self.assertTrue(detect.plans_multi_slice_work("Write a migration plan for the API move."))

    def test_single_file_edit_stays_silent(self) -> None:
        self.assertFalse(detect.plans_multi_slice_work("Edit this one file to add the import."))

    def test_typo_fix_stays_silent(self) -> None:
        self.assertFalse(detect.plans_multi_slice_work("Fix the typo in README.md."))

    def test_split_scope_name_question_stays_silent(self) -> None:
        self.assertFalse(detect.plans_multi_slice_work("What does split-scope do?"))


class TestClaudePromptEntrypoint(SplitScopeCase):
    def assert_claude_fires(self, prompt: str) -> None:
        out, err, code = run_json(
            claude_prompt_submit.main,
            {"prompt": prompt, "session_id": "claude-positive"},
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(
            data["hookSpecificOutput"]["additionalContext"],
            REMINDER,
        )
        self.assertEqual(err, "")

    def assert_claude_silent(self, prompt: str) -> None:
        out, err, code = run_json(
            claude_prompt_submit.main,
            {"prompt": prompt, "session_id": "claude-negative"},
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_real_claude_entrypoint_fires_on_multiple_prs(self) -> None:
        self.assert_claude_fires("Please plan multiple PRs for this refactor.")

    def test_real_claude_entrypoint_fires_on_stacked_prs(self) -> None:
        self.assert_claude_fires("Create stacked PRs for the API migration.")

    def test_real_claude_entrypoint_fires_on_plan_the_migration(self) -> None:
        self.assert_claude_fires("Plan the migration before changing code.")

    def test_real_claude_entrypoint_prints_nothing_on_single_file_edit(self) -> None:
        self.assert_claude_silent("Change the label in this single file.")

    def test_real_claude_entrypoint_prints_nothing_on_typo_fix(self) -> None:
        self.assert_claude_silent("Fix the recieve typo in README.md.")

    def test_real_claude_entrypoint_prints_nothing_on_split_scope_question(self) -> None:
        self.assert_claude_silent("What does split-scope do?")

    def test_malformed_json_fails_open_with_empty_stdout(self) -> None:
        cases = (
            (claude_prompt_submit.main, "split-scope claude_prompt_submit fail-open"),
            (codex_prompt_submit.main, "split-scope codex_prompt_submit fail-open"),
            (cursor_before_submit.main, "split-scope cursor_before_submit fail-open"),
            (cursor_post_tool_use.main, "split-scope cursor_post_tool_use fail-open"),
        )
        for main, marker in cases:
            with self.subTest(marker=marker):
                out, err, code = run_main(main, "not-json")
                self.assertEqual(code, 0)
                self.assertEqual(out, "")
                self.assertIn(marker, err)


class TestCursorHandoff(SplitScopeCase):
    def test_cursor_pending_prompt_injects_once_on_first_post_tool_use(self) -> None:
        out, err, code = run_json(
            cursor_before_submit.main,
            {"prompt": "Break this into PRs.", "session_id": "cursor-1"},
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "cursor-1", "tool_name": "Edit"},
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["additional_context"], REMINDER)
        self.assertEqual(err, "")

        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "cursor-1", "tool_name": "Edit"},
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_cursor_before_submit_prints_nothing_on_nonmatch(self) -> None:
        out, err, code = run_json(
            cursor_before_submit.main,
            {"prompt": "Fix this one typo.", "session_id": "cursor-quiet"},
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
