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

    def test_effective_start_dir_follows_leading_cd(self):
        # Caught live: `cd other-repo && gh pr edit ...` still evaluated
        # against the session's launch cwd without this -- PreToolUse fires
        # before the command runs, so it can't otherwise see the `cd`.
        self.assertEqual(
            detect.effective_start_dir("/session/start", "cd /elsewhere && gh pr edit 1 --body x"),
            "/elsewhere",
        )

    def test_effective_start_dir_resolves_relative_cd(self):
        self.assertEqual(
            detect.effective_start_dir("/session/start", "cd ../sibling && gh pr create"),
            "/session/start/../sibling",
        )

    def test_effective_start_dir_does_not_match_command_without_leading_cd(self):
        self.assertEqual(
            detect.effective_start_dir("/session/start", "gh pr edit 1 --body x"),
            "/session/start",
        )


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

    def test_blocks_via_leading_cd_into_repo_with_tool(self):
        # Live incident: cwd stayed the session's launch dir (which has the
        # tool) while `cd` targeted a DIFFERENT repo -- must resolve to the
        # cd target's own tool presence, not the payload cwd's.
        with _repo_with_tool() as repo, _repo_without_tool() as session_cwd:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": f"cd {repo} && gh pr create --title x"},
                "cwd": session_cwd,
            }
            with self.assertRaises(SystemExit) as ctx:
                err = io.StringIO()
                with redirect_stderr(err):
                    with _stdin(json.dumps(payload)):
                        claude_pretooluse.main()
            self.assertEqual(ctx.exception.code, 2)

    def test_allows_via_leading_cd_into_repo_without_tool(self):
        # Inverse: session cwd has the tool, but the command explicitly cd's
        # into a repo that doesn't -- must fail open there, not block based
        # on the unrelated session-launch directory.
        with _repo_with_tool() as session_cwd, _repo_without_tool() as repo:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": f"cd {repo} && gh pr create --title x"},
                "cwd": session_cwd,
            }
            with _stdin(json.dumps(payload)):
                claude_pretooluse.main()  # must not raise SystemExit

    def test_codex_nested_workdir_outranks_session_cwd(self):
        with _repo_with_tool() as session_cwd, _repo_without_tool() as target:
            source = (
                'const r = await tools.exec_command({'
                f'"cmd":"gh pr edit 100 --body-file /tmp/body.md","workdir":"{target}"'
                '});'
            )
            payload = {
                "tool_name": "exec_command",
                "tool_input": {"input": source},
                "cwd": session_cwd,
            }
            with _stdin(json.dumps(payload)):
                claude_pretooluse.main()  # target has no sanctioned helper, so fail open

    def test_codex_nested_workdir_can_select_repo_with_tool(self):
        with _repo_without_tool() as session_cwd, _repo_with_tool() as target:
            source = (
                'const r = await tools.exec_command({'
                f'"cmd":"gh pr edit 100 --body-file /tmp/body.md","workdir":"{target}"'
                '});'
            )
            payload = {
                "tool_name": "exec_command",
                "tool_input": {"input": source},
                "cwd": session_cwd,
            }
            with self.assertRaises(SystemExit) as ctx:
                with redirect_stderr(io.StringIO()):
                    with _stdin(json.dumps(payload)):
                        claude_pretooluse.main()
            self.assertEqual(ctx.exception.code, 2)

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
