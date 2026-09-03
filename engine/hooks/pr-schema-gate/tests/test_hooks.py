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
import time
import unittest
from contextlib import redirect_stderr

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402


_MODULE_STATE_DIR: tempfile.TemporaryDirectory | None = None
_PREV_STATE_DIR: str | None = None


def setUpModule():
    """Redirect the guard's state directory into a throwaway dir.

    No test may read, write, or leave behind a developer's real
    pending-follow-up state.
    """
    global _MODULE_STATE_DIR, _PREV_STATE_DIR
    _MODULE_STATE_DIR = tempfile.TemporaryDirectory()
    _PREV_STATE_DIR = os.environ.get(detect.STATE_DIR_ENV)
    os.environ[detect.STATE_DIR_ENV] = _MODULE_STATE_DIR.name


def tearDownModule():
    if _PREV_STATE_DIR is None:
        os.environ.pop(detect.STATE_DIR_ENV, None)
    else:
        os.environ[detect.STATE_DIR_ENV] = _PREV_STATE_DIR
    if _MODULE_STATE_DIR is not None:
        _MODULE_STATE_DIR.cleanup()


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

    def test_find_repo_flag_matches_long_form(self):
        self.assertEqual(
            detect.find_repo_flag(
                "gh pr edit 209 --repo EdbertChan/catstack --body-file x.md"
            ),
            "EdbertChan/catstack",
        )

    def test_find_repo_flag_matches_short_form(self):
        self.assertEqual(
            detect.find_repo_flag("gh pr create -R EdbertChan/catstack --title x"),
            "EdbertChan/catstack",
        )

    def test_find_repo_flag_absent_returns_none(self):
        self.assertIsNone(detect.find_repo_flag("gh pr edit 209 --body-file x.md"))

    def test_sibling_repo_dir_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = root
            try:
                self.assertIsNone(detect.sibling_repo_dir("EdbertChan/catstack"))
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)

    def test_sibling_repo_dir_present_returns_path(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = root
            try:
                expected = os.path.join(root, "catstack")
                os.makedirs(expected)
                self.assertEqual(
                    detect.sibling_repo_dir("EdbertChan/catstack"), expected
                )
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)


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

    def test_blocks_via_repo_flag_into_sibling_repo_with_tool(self):
        with tempfile.TemporaryDirectory() as checkouts_root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = checkouts_root
            try:
                sibling = os.path.join(checkouts_root, "catstack")
                os.makedirs(os.path.join(sibling, "scripts"))
                os.makedirs(os.path.join(sibling, ".git"))
                with open(os.path.join(sibling, "scripts", "create-pr.mjs"), "w") as f:
                    f.write("// stub\n")
                with _repo_without_tool() as session_cwd:
                    payload = {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": "gh pr edit 209 --repo EdbertChan/catstack "
                            "--body-file /tmp/pr209-body-new.md"
                        },
                        "cwd": session_cwd,
                    }
                    with self.assertRaises(SystemExit) as ctx:
                        with redirect_stderr(io.StringIO()):
                            with _stdin(json.dumps(payload)):
                                claude_pretooluse.main()
                    self.assertEqual(ctx.exception.code, 2)
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)

    def test_allows_via_repo_flag_into_sibling_repo_without_tool(self):
        with tempfile.TemporaryDirectory() as checkouts_root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = checkouts_root
            try:
                sibling = os.path.join(checkouts_root, "catstack")
                os.makedirs(os.path.join(sibling, ".git"))
                with _repo_with_tool() as session_cwd:
                    payload = {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": "gh pr edit 209 --repo EdbertChan/catstack "
                            "--body-file /tmp/pr209-body-new.md"
                        },
                        "cwd": session_cwd,
                    }
                    with _stdin(json.dumps(payload)):
                        claude_pretooluse.main()
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)

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


COMMAND_LITERALS_ARE_SPLIT = """The blocked commands are assembled at runtime,
never written as one literal. This hook matches raw payload text, so spelling
them out in a file that tools routinely cat and grep is exactly the known
false positive detect.py documents."""

GH_PR_CREATE_CMD = "gh pr " + "create --title x --base main"
GH_PR_EDIT_BODY_CMD = "gh pr " + "edit 10737 --body-file /tmp/body.md"
STACK_PUSH_CMD = "mergify stack push"
FOLLOWUP_CMD = 'node scripts/create-pr.mjs --title "x" --base main --body-file /tmp/b.md --update-existing'


def _bash(command: str, cwd: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})


def _run(command: str, cwd: str):
    """Run the hook on one command; return (blocked, stderr_text)."""
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            with _stdin(_bash(command, cwd)):
                claude_pretooluse.main()
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True, err.getvalue()
    return False, err.getvalue()


class StackFollowUpBase(unittest.TestCase):
    """Per-test isolation of the guard's state directory, on top of the module fixture."""

    def setUp(self):
        self._state = tempfile.TemporaryDirectory()
        self._prev = os.environ.get(detect.STATE_DIR_ENV)
        os.environ[detect.STATE_DIR_ENV] = self._state.name
        self.addCleanup(self._state.cleanup)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._prev is None:
            os.environ.pop(detect.STATE_DIR_ENV, None)
        else:
            os.environ[detect.STATE_DIR_ENV] = self._prev


class TestStackFollowUpDetect(StackFollowUpBase):
    def test_publication_command_recognized(self):
        self.assertEqual(detect.find_publication_command(STACK_PUSH_CMD), "mergify stack push")

    def test_unrelated_command_is_not_a_publication(self):
        self.assertIsNone(detect.find_publication_command("git status && npm test"))

    def test_sanctioned_followup_recognized(self):
        self.assertTrue(detect.is_sanctioned_followup(FOLLOWUP_CMD))

    def test_unrelated_command_is_not_a_followup(self):
        self.assertFalse(detect.is_sanctioned_followup("git status && npm test"))

    def test_mark_then_read_then_clear_round_trip(self):
        with _repo_with_tool() as repo:
            self.assertIsNone(detect.read_pending(repo))
            detect.mark_pending(repo, now=1000.0)
            self.assertEqual(detect.read_pending(repo, now=1000.0), 1000.0)
            detect.clear_pending(repo)
            self.assertIsNone(detect.read_pending(repo))

    def test_clear_pending_on_absent_state_is_a_no_op(self):
        with _repo_with_tool() as repo:
            detect.clear_pending(repo)
            self.assertIsNone(detect.read_pending(repo))

    def test_pending_expires_after_ttl(self):
        with _repo_with_tool() as repo:
            detect.mark_pending(repo, now=1000.0)
            fresh = 1000.0 + detect.PENDING_TTL_SECONDS - 1
            self.assertIsNotNone(detect.read_pending(repo, now=fresh))
            stale = 1000.0 + detect.PENDING_TTL_SECONDS + 1
            self.assertIsNone(detect.read_pending(repo, now=stale))

    def test_malformed_json_state_reads_as_not_pending(self):
        with _repo_with_tool() as repo:
            path = detect.pending_state_path(repo)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{not json at all")
            self.assertIsNone(detect.read_pending(repo))

    def test_state_with_wrong_field_type_reads_as_not_pending(self):
        with _repo_with_tool() as repo:
            path = detect.pending_state_path(repo)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"pending_since": "yesterday"}, f)
            self.assertIsNone(detect.read_pending(repo))

    def test_state_missing_field_reads_as_not_pending(self):
        with _repo_with_tool() as repo:
            path = detect.pending_state_path(repo)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"repo": repo}, f)
            self.assertIsNone(detect.read_pending(repo))

    def test_future_dated_state_reads_as_not_pending(self):
        with _repo_with_tool() as repo:
            detect.mark_pending(repo, now=5000.0)
            self.assertIsNone(detect.read_pending(repo, now=1000.0))

    def test_state_is_per_repo_root(self):
        with _repo_with_tool() as one, _repo_with_tool() as two:
            detect.mark_pending(one, now=1000.0)
            self.assertIsNotNone(detect.read_pending(one, now=1000.0))
            self.assertIsNone(detect.read_pending(two, now=1000.0))

    def test_state_file_lives_outside_the_repo(self):
        """The guard must never add an untracked file to the worktree it polices."""
        with _repo_with_tool() as repo:
            detect.mark_pending(repo)
            self.assertFalse(
                os.path.abspath(detect.pending_state_path(repo)).startswith(os.path.abspath(repo))
            )


class TestStackFollowUpHook(StackFollowUpBase):
    def test_first_stack_push_is_allowed_and_arms_pending(self):
        with _repo_with_tool() as repo:
            blocked, _ = _run(STACK_PUSH_CMD, repo)
            self.assertFalse(blocked)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_second_stack_push_is_blocked_while_follow_up_is_owed(self):
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            blocked, err = _run(STACK_PUSH_CMD, repo)
            self.assertTrue(blocked)
            self.assertIn("create-pr.mjs", err)

    def test_sanctioned_follow_up_clears_pending_and_reopens_publication(self):
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            blocked, _ = _run(FOLLOWUP_CMD, repo)
            self.assertFalse(blocked)
            self.assertIsNone(detect.read_pending(repo))
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])

    def test_unrelated_command_before_publication_is_allowed_and_arms_nothing(self):
        with _repo_with_tool() as repo:
            blocked, _ = _run("git status && npm test", repo)
            self.assertFalse(blocked)
            self.assertIsNone(detect.read_pending(repo))

    def test_unrelated_command_while_pending_is_allowed_and_keeps_pending(self):
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            blocked, _ = _run("grep -r TODO .", repo)
            self.assertFalse(blocked)
            self.assertIsNotNone(detect.read_pending(repo))
            self.assertTrue(_run(STACK_PUSH_CMD, repo)[0])

    def test_malformed_state_fails_open_on_second_push(self):
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            path = detect.pending_state_path(repo)
            with open(path, "w") as f:
                f.write("}{ truncated")
            blocked, _ = _run(STACK_PUSH_CMD, repo)
            self.assertFalse(blocked)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_expired_pending_fails_open_on_next_push(self):
        with _repo_with_tool() as repo:
            detect.mark_pending(repo, now=time.time() - detect.PENDING_TTL_SECONDS - 60)
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])

    def test_repo_without_create_pr_tool_never_arms_pending(self):
        with _repo_without_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            self.assertIsNone(detect.read_pending(repo))

    def test_pending_in_one_repo_does_not_block_another(self):
        with _repo_with_tool() as one, _repo_with_tool() as two:
            self.assertFalse(_run(STACK_PUSH_CMD, one)[0])
            self.assertFalse(_run(STACK_PUSH_CMD, two)[0])

    def test_direct_pr_create_still_blocked_with_the_direct_message(self):
        with _repo_with_tool() as repo:
            blocked, err = _run(GH_PR_CREATE_CMD, repo)
            self.assertTrue(blocked)
            self.assertIn("bypasses the make-pr/draft-pr PR-body schema", err)

    def test_direct_pr_edit_body_still_blocked_while_pending(self):
        """The follow-up guard must not shadow or soften the original block."""
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            blocked, err = _run(GH_PR_EDIT_BODY_CMD, repo)
            self.assertTrue(blocked)
            self.assertIn("bypasses the make-pr/draft-pr PR-body schema", err)

    def test_direct_writer_does_not_clear_pending(self):
        with _repo_with_tool() as repo:
            self.assertFalse(_run(STACK_PUSH_CMD, repo)[0])
            self.assertTrue(_run(GH_PR_CREATE_CMD, repo)[0])
            self.assertIsNotNone(detect.read_pending(repo))


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
