#!/usr/bin/env python3
"""Unit tests for pr-schema-gate.

Run: python3 -m unittest discover -s hooks/pr-schema-gate/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402


def _repo_with_tool() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    os.makedirs(os.path.join(tmp.name, "scripts"))
    os.makedirs(os.path.join(tmp.name, ".git"))
    with open(os.path.join(tmp.name, "scripts", "create-pr.mjs"), "w") as f:
        f.write("// stub\n")
    return tmp


def _repo_without_tool() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    os.makedirs(os.path.join(tmp.name, ".git"))
    return tmp


class TestDetect(unittest.TestCase):
    def test_gh_pr_create_matches(self):
        self.assertEqual(detect.find_blocked_command('gh pr create --title "x" --base main'), "gh pr create")

    def test_gh_pr_edit_with_body_matches(self):
        self.assertEqual(
            detect.find_blocked_command("gh pr edit 10737 --body 'placeholder'"), "gh pr edit --body"
        )

    def test_gh_pr_edit_with_body_file_matches(self):
        self.assertEqual(
            detect.find_blocked_command("gh pr edit 10737 --body-file .pr-body-3.md"), "gh pr edit --body"
        )

    def test_gh_pr_edit_title_only_does_not_match(self):
        self.assertIsNone(detect.find_blocked_command("gh pr edit 10737 --title 'new title'"))

    def test_json_wrapped_command_still_matches(self):
        # Real Claude/Cursor payload shape: the command sits inside
        # tool_input.command, quote-adjacent either way. A fix that tried to
        # exclude quote-adjacent "gh" broke this real case identically to
        # the false positive below -- see detect.py's module docstring.
        payload = '{"tool_name": "Bash", "tool_input": {"command": "gh pr create --title x --base main"}}'
        self.assertEqual(detect.find_blocked_command(payload), "gh pr create")

    def test_known_false_positive_inert_text_also_matches(self):
        # Documents the known limitation (module docstring), not a bug to
        # silently "fix" -- a command that merely contains this text as
        # inert data (a heredoc feeding a test payload, like the live
        # incident that surfaced this) matches identically to a real call.
        inert = "python3 script.py <<< '{\"tool_input\": {\"command\": \"gh pr create --title x\"}}'"
        self.assertEqual(detect.find_blocked_command(inert), "gh pr create")

    def test_gh_api_pulls_from_create_pr_mjs_does_not_match(self):
        # scripts/create-pr.mjs's own subprocess call -- must never self-block.
        self.assertIsNone(
            detect.find_blocked_command("gh api repos/org/repo/pulls --method POST --input -")
        )

    def test_mergify_stack_push_does_not_match(self):
        # Legitimate step 1 of the stack flow; only the bare-body writers are blocked.
        self.assertIsNone(detect.find_blocked_command("mergify stack push"))

    def test_repo_root_found_when_tool_present(self):
        with _repo_with_tool() as repo:
            self.assertEqual(detect.repo_root_with_create_pr_tool(repo), repo)

    def test_repo_root_none_when_tool_absent(self):
        with _repo_without_tool() as repo:
            self.assertIsNone(detect.repo_root_with_create_pr_tool(repo))

    def test_repo_root_found_from_subdirectory(self):
        with _repo_with_tool() as repo:
            sub = os.path.join(repo, "packages", "app")
            os.makedirs(sub)
            self.assertEqual(detect.repo_root_with_create_pr_tool(sub), repo)


class TestClaudePreToolUse(unittest.TestCase):
    def test_blocks_gh_pr_create_in_repo_with_tool(self):
        with _repo_with_tool() as repo:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": 'gh pr create --title x --base main'},
                "cwd": repo,
            }
            with self.assertRaises(SystemExit) as ctx:
                err = io.StringIO()
                with redirect_stderr(err):
                    with _stdin(json.dumps(payload)):
                        claude_pretooluse.main()
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("create-pr.mjs", err.getvalue())

    def test_allows_gh_pr_create_when_repo_has_no_tool(self):
        with _repo_without_tool() as repo:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr create --title x --base main"},
                "cwd": repo,
            }
            with _stdin(json.dumps(payload)):
                claude_pretooluse.main()  # must not raise SystemExit

    def test_allows_non_bash_tool_even_if_content_mentions_gh_pr_create(self):
        # A Write call whose file content documents "gh pr create" must never block.
        with _repo_with_tool() as repo:
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": "README.md", "content": "Do not run gh pr create directly."},
                "cwd": repo,
            }
            with _stdin(json.dumps(payload)):
                claude_pretooluse.main()  # must not raise SystemExit

    def test_allows_mergify_stack_push(self):
        with _repo_with_tool() as repo:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "mergify stack push"},
                "cwd": repo,
            }
            with _stdin(json.dumps(payload)):
                claude_pretooluse.main()  # must not raise SystemExit


class _stdin:
    def __init__(self, text: str):
        self._text = text
        self._old = None

    def __enter__(self):
        self._old = sys.stdin
        sys.stdin = io.StringIO(self._text)

    def __exit__(self, *exc):
        sys.stdin = self._old


if __name__ == "__main__":
    unittest.main()
