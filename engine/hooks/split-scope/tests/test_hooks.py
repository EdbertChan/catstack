#!/usr/bin/env python3
"""Unit tests for split-scope inject hooks.

Run: python3 -m unittest discover -s engine/hooks/split-scope/tests -v
"""
from __future__ import annotations

import io
import json
import os
import subprocess
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


REMINDER = (
    "split-scope: this prompt plans multi-slice work. Before writing the plan "
    "or PR stack, read the split-scope skill "
    "(product/skills/split-scope/SKILL.md, or the installed split-scope skill) "
    "and give each slice one review claim with a user-confirmed safety invariant."
)

POSITIVE_PROMPTS = [
    "Please make a PR stack for the auth migration.",
    "Plan a migration that splits this into reviewable pieces.",
    "Break this into PRs before implementation.",
]

NEGATIVE_PROMPTS = [
    "Fix this single typo in README.md.",
    "Edit only app.py to rename this local variable.",
    "What does split-scope do?",
]


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
        detect.STATE_DIR = self.tmp.name
        state.STATE_DIR = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestDetect(SplitScopeCase):
    def test_pr_stack_fires(self) -> None:
        self.assertTrue(detect.plans_multi_slice_work("Ship this as a PR stack."))

    def test_multiple_prs_fire(self) -> None:
        self.assertTrue(detect.plans_multi_slice_work("This needs multiple PRs."))

    def test_question_about_split_scope_is_silent(self) -> None:
        self.assertFalse(detect.plans_multi_slice_work("What does split-scope do?"))

    def test_single_file_edit_is_silent(self) -> None:
        self.assertFalse(detect.plans_multi_slice_work("Fix a typo in one file."))


class TestClaudePromptEntrypoint(SplitScopeCase):
    def test_claude_prompt_fires_with_exact_reminder_text(self) -> None:
        for prompt in POSITIVE_PROMPTS:
            with self.subTest(prompt=prompt):
                result = subprocess.run(
                    [sys.executable, os.path.join(HOOKS_DIR, "claude_prompt_submit.py")],
                    input=json.dumps({"prompt": prompt, "session_id": "positive"}),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                data = json.loads(result.stdout)
                self.assertEqual(
                    data["hookSpecificOutput"]["additionalContext"],
                    REMINDER,
                )

    def test_claude_prompt_prints_nothing_for_silent_prompts(self) -> None:
        for prompt in NEGATIVE_PROMPTS:
            with self.subTest(prompt=prompt):
                result = subprocess.run(
                    [sys.executable, os.path.join(HOOKS_DIR, "claude_prompt_submit.py")],
                    input=json.dumps({"prompt": prompt, "session_id": "negative"}),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, "")


class TestCodexPromptEntrypoint(SplitScopeCase):
    def test_codex_prompt_fires_with_exact_reminder_text(self) -> None:
        out, err, code = run_json(
            codex_prompt_submit.main,
            {"prompt": "Use stacked PRs for this change.", "session_id": "codex"},
        )
        self.assertEqual((err, code), ("", 0))
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], REMINDER)

    def test_codex_prompt_prints_nothing_for_silent_prompt(self) -> None:
        out, err, code = run_json(
            codex_prompt_submit.main,
            {"prompt": "Fix this single typo in README.md.", "session_id": "codex-silent"},
        )
        self.assertEqual((out, err, code), ("", "", 0))


class TestCursorPromptDelivery(SplitScopeCase):
    def test_cursor_prompt_is_delivered_on_first_post_tool_use(self) -> None:
        out, err, code = run_json(
            cursor_before_submit.main,
            {"prompt": "Create a stack of PRs for this migration.", "session_id": "cursor"},
        )
        self.assertEqual((out, err, code), ("", "", 0))
        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "cursor", "tool_name": "Read", "tool_input": {"path": "a.py"}},
        )
        self.assertEqual((err, code), ("", 0))
        self.assertEqual(json.loads(out), {"additional_context": REMINDER})
        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "cursor", "tool_name": "Read", "tool_input": {"path": "b.py"}},
        )
        self.assertEqual((out, err, code), ("", "", 0))

    def test_cursor_nonmatching_prompt_stays_silent(self) -> None:
        out, err, code = run_json(
            cursor_before_submit.main,
            {"prompt": "What does split-scope do?", "session_id": "cursor-silent"},
        )
        self.assertEqual((out, err, code), ("", "", 0))
        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "cursor-silent", "tool_name": "Read"},
        )
        self.assertEqual((out, err, code), ("", "", 0))

    def test_malformed_state_fails_open_without_stdout(self) -> None:
        path = state.state_path({"session_id": "bad-state"})
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{")
        out, err, code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "bad-state", "tool_name": "Read"},
        )
        self.assertEqual((out, err, code), ("", "", 0))


class TestFailOpen(SplitScopeCase):
    def test_malformed_payload_fails_open_with_context_on_stderr(self) -> None:
        for main in (
            claude_prompt_submit.main,
            codex_prompt_submit.main,
            cursor_before_submit.main,
            cursor_post_tool_use.main,
        ):
            with self.subTest(main=main.__module__):
                out, err, code = run_main(main, "{not json")
                self.assertEqual(code, 0)
                self.assertEqual(out, "")
                self.assertIn("split-scope", err)
                self.assertIn("unreadable hook input", err)

    def test_entrypoint_detector_exception_fails_open_without_stdout(self) -> None:
        with patch("claude_prompt_submit.plans_multi_slice_work", side_effect=RuntimeError("boom")):
            out, err, code = run_json(
                claude_prompt_submit.main,
                {"prompt": "make a pr stack", "session_id": "explode"},
            )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("split-scope claude_prompt_submit", err)


if __name__ == "__main__":
    unittest.main()
