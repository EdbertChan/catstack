#!/usr/bin/env python3
"""Unit tests for pr-schema-gate: classification, target resolution, and follow-up state.

Run: python3 -m unittest discover -s engine/hooks/pr-schema-gate/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
from shell_model import Command  # noqa: E402

COMMAND_LITERALS_ARE_SPLIT = """PR commands are assembled at runtime, never written
as one literal, because other installed hooks still match raw command text and
tools routinely cat and grep this file."""

GH = "g" + "h"
GH_PR_CREATE_CMD = GH + " pr create --title x --base main"
GH_PR_EDIT_BODY_CMD = GH + " pr edit 10737 --body-file /tmp/body.md"
STACK_PUSH_CMD = "mergify stack push"
FOLLOWUP_CMD = 'node scripts/create-pr.mjs --title "x" --base main --body-file /tmp/b.md --update-existing'


def setUpModule():
    global _MODULE_STATE_DIR, _PREV_STATE_DIR
    _MODULE_STATE_DIR = tempfile.TemporaryDirectory()
    _PREV_STATE_DIR = os.environ.get(detect.STATE_DIR_ENV)
    os.environ[detect.STATE_DIR_ENV] = _MODULE_STATE_DIR.name


def tearDownModule():
    if _PREV_STATE_DIR is None:
        os.environ.pop(detect.STATE_DIR_ENV, None)
    else:
        os.environ[detect.STATE_DIR_ENV] = _PREV_STATE_DIR
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


def _cmd(*argv: str, cwd: str = "/s") -> Command:
    return Command(tuple(argv), cwd)


class _stdin:
    def __init__(self, text: str):
        self._text = text
        self._old = None

    def __enter__(self):
        self._old = sys.stdin
        sys.stdin = io.StringIO(self._text)

    def __exit__(self, *exc):
        sys.stdin = self._old


def _run_payload(payload: dict):
    """Run the hook once; return (advised, stderr). Any SystemExit fails the test."""
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        with _stdin(json.dumps(payload)):
            claude_pretooluse.main()
    return bool(err.getvalue()), err.getvalue()


def _run(command: str, cwd: str):
    return _run_payload({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})


class TestClassify(unittest.TestCase):
    def test_pr_create_is_a_text_write(self):
        write = detect.classify_pr_text_write(_cmd(GH, "pr", "create", "--title", "x"))
        self.assertEqual((write.label, write.body_file), ("gh pr create", None))

    def test_pr_edit_inline_body_is_a_text_write_without_a_file(self):
        write = detect.classify_pr_text_write(_cmd(GH, "pr", "edit", "7", "--body", "placeholder"))
        self.assertEqual((write.label, write.body_file), ("gh pr edit --body", None))

    def test_pr_edit_body_file_long_short_and_equals_forms(self):
        for argv in (
            (GH, "pr", "edit", "7", "--body-file", "b.md"),
            (GH, "pr", "edit", "7", "-F", "b.md"),
            (GH, "pr", "edit", "7", "--body-file=b.md"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(detect.classify_pr_text_write(_cmd(*argv)).body_file, "b.md")

    def test_pr_edit_body_file_from_stdin_has_no_file(self):
        write = detect.classify_pr_text_write(_cmd(GH, "pr", "edit", "7", "--body-file", "-"))
        self.assertIsNone(write.body_file)

    def test_pr_edit_title_only_is_not_a_text_write(self):
        self.assertIsNone(detect.classify_pr_text_write(_cmd(GH, "pr", "edit", "7", "--title", "t")))

    def test_repo_flag_long_short_and_equals_forms(self):
        for argv in (
            (GH, "pr", "edit", "209", "--repo", "EdbertChan/catstack", "--body-file", "x.md"),
            (GH, "pr", "create", "-R", "EdbertChan/catstack", "--title", "x"),
            (GH, "pr", "create", "--repo=EdbertChan/catstack"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(detect.classify_pr_text_write(_cmd(*argv)).repo_spec, "EdbertChan/catstack")

    def test_gh_api_patch_body_file_field(self):
        write = detect.classify_pr_text_write(
            _cmd(GH, "api", "-X", "PATCH", "repos/o/r/pulls/7", "-F", "body=@b.md")
        )
        self.assertEqual((write.label, write.body_file), ("gh api pulls body", "b.md"))

    def test_gh_api_body_field_in_equals_form_as_last_argument(self):
        write = detect.classify_pr_text_write(_cmd(GH, "api", "repos/o/r/pulls/7", "--field=body=@b.md"))
        self.assertEqual(write.body_file, "b.md")

    def test_gh_api_raw_body_field_is_inline(self):
        write = detect.classify_pr_text_write(_cmd(GH, "api", "repos/o/r/pulls/7", "-f", "body=@not-a-file"))
        self.assertIsNone(write.body_file)

    def test_gh_api_read_is_not_a_text_write(self):
        self.assertIsNone(detect.classify_pr_text_write(_cmd(GH, "api", "repos/o/r/pulls/7", "--jq", ".body")))

    def test_gh_api_title_only_patch_is_not_a_text_write(self):
        self.assertIsNone(detect.classify_pr_text_write(
            _cmd(GH, "api", "-X", "PATCH", "repos/o/r/pulls/7", "-f", "title=x")
        ))

    def test_create_pr_mjs_subprocess_shape_is_not_a_text_write(self):
        self.assertIsNone(detect.classify_pr_text_write(
            _cmd(GH, "api", "repos/org/repo/pulls", "--method", "POST", "--input", "-")
        ))

    def test_gh_api_on_issues_is_not_a_pr_text_write(self):
        self.assertIsNone(detect.classify_pr_text_write(
            _cmd(GH, "api", "repos/o/r/issues/7/comments", "-f", "body=hi")
        ))

    def test_other_programs_are_not_text_writes(self):
        self.assertIsNone(detect.classify_pr_text_write(_cmd("grep", "-rn", GH + " pr edit --body", ".")))

    def test_stack_push_forms(self):
        self.assertTrue(detect.is_stack_push(_cmd("mergify", "stack", "push")))
        self.assertTrue(detect.is_stack_push(_cmd("npx", "mergify", "stack", "push")))
        self.assertFalse(detect.is_stack_push(_cmd("mergify", "stack", "push", "--dry-run")))
        self.assertFalse(detect.is_stack_push(_cmd("npx", "mergify", "stack", "push", "--dry-run", "--branch-prefix", "s")))
        self.assertFalse(detect.is_stack_push(_cmd("echo", "mergify", "stack", "push")))

    def test_create_pr_followup_forms(self):
        self.assertTrue(detect.is_create_pr_followup(_cmd("node", "scripts/create-pr.mjs", "--update-existing")))
        self.assertTrue(detect.is_create_pr_followup(_cmd("./scripts/create-pr.mjs")))
        self.assertFalse(detect.is_create_pr_followup(_cmd("cat", "scripts/create-pr.mjs")))

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
                self.assertEqual(detect.sibling_repo_dir("EdbertChan/catstack"), expected)
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)


class TestTargetResolution(unittest.TestCase):
    def test_never_exits_nonzero_for_any_pr_write_in_scope(self):
        with _repo_with_tool() as repo:
            for command in (GH_PR_CREATE_CMD, GH_PR_EDIT_BODY_CMD, STACK_PUSH_CMD, STACK_PUSH_CMD):
                with self.subTest(command=command):
                    advised, _ = _run(command, repo)
                    self.assertTrue(advised)

    def test_repo_without_tool_is_silent(self):
        with _repo_without_tool() as repo:
            self.assertEqual(_run(GH_PR_CREATE_CMD, repo), (False, ""))

    def test_cd_into_repo_with_tool_is_in_scope(self):
        with _repo_with_tool() as repo, _repo_without_tool() as session_cwd:
            self.assertTrue(_run(f"cd {repo} && {GH_PR_CREATE_CMD}", session_cwd)[0])

    def test_cd_into_repo_without_tool_is_out_of_scope(self):
        with _repo_with_tool() as session_cwd, _repo_without_tool() as repo:
            self.assertFalse(_run(f"cd {repo} && {GH_PR_CREATE_CMD}", session_cwd)[0])

    def test_codex_nested_workdir_outranks_session_cwd(self):
        with _repo_with_tool() as session_cwd, _repo_without_tool() as target:
            source = ('const r = await tools.exec_command({'
                      f'"cmd":"{GH_PR_EDIT_BODY_CMD}","workdir":"{target}"' '});')
            payload = {"tool_name": "exec_command", "tool_input": {"input": source}, "cwd": session_cwd}
            self.assertFalse(_run_payload(payload)[0])

    def test_codex_nested_workdir_can_select_repo_with_tool(self):
        with _repo_without_tool() as session_cwd, _repo_with_tool() as target:
            source = ('const r = await tools.exec_command({'
                      f'"cmd":"{GH_PR_EDIT_BODY_CMD}","workdir":"{target}"' '});')
            payload = {"tool_name": "exec_command", "tool_input": {"input": source}, "cwd": session_cwd}
            self.assertTrue(_run_payload(payload)[0])

    def test_repo_flag_into_sibling_repo_with_tool_is_in_scope(self):
        with tempfile.TemporaryDirectory() as checkouts_root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = checkouts_root
            try:
                sibling = os.path.join(checkouts_root, "catstack")
                os.makedirs(os.path.join(sibling, "scripts"))
                os.makedirs(os.path.join(sibling, ".git"))
                with open(os.path.join(sibling, "scripts", "create-pr.mjs"), "w") as f:
                    f.write("// stub\n")
                with _repo_without_tool() as session_cwd:
                    command = GH + " pr edit 209 --repo EdbertChan/catstack --body-file /tmp/pr209-body-new.md"
                    self.assertTrue(_run(command, session_cwd)[0])
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)

    def test_repo_flag_into_sibling_repo_without_tool_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as checkouts_root:
            os.environ[detect.GITHUB_CHECKOUTS_ROOT_ENV] = checkouts_root
            try:
                os.makedirs(os.path.join(checkouts_root, "catstack", ".git"))
                with _repo_with_tool() as session_cwd:
                    command = GH + " pr edit 209 --repo EdbertChan/catstack --body-file /tmp/pr209-body-new.md"
                    self.assertFalse(_run(command, session_cwd)[0])
            finally:
                os.environ.pop(detect.GITHUB_CHECKOUTS_ROOT_ENV, None)

    def test_non_shell_tool_is_never_evaluated(self):
        with _repo_with_tool() as repo:
            payload = {"tool_name": "Write",
                       "tool_input": {"file_path": "README.md", "content": "Do not run " + GH_PR_CREATE_CMD},
                       "cwd": repo}
            self.assertEqual(_run_payload(payload), (False, ""))

    def test_inert_text_that_only_mentions_a_pr_write_is_silent(self):
        with _repo_with_tool() as repo:
            for command in (
                f"grep -rn '{GH} pr edit --body' engine/",
                f"python3 script.py <<< '{{\"command\": \"{GH_PR_CREATE_CMD}\"}}'",
                f"echo \"{GH_PR_EDIT_BODY_CMD}\"",
            ):
                with self.subTest(command=command):
                    self.assertEqual(_run(command, repo), (False, ""))

    def test_unparseable_command_in_scope_says_it_was_not_checked(self):
        with _repo_with_tool() as repo:
            advised, err = _run("echo 'unbalanced", repo)
            self.assertTrue(advised)
            self.assertIn("could not parse", err)

    def test_unparseable_command_out_of_scope_is_silent(self):
        with _repo_without_tool() as repo:
            self.assertEqual(_run("echo 'unbalanced", repo), (False, ""))

    def test_unreadable_payload_reports_and_does_not_raise(self):
        err = io.StringIO()
        with redirect_stderr(err), _stdin("{not json"):
            claude_pretooluse.main()
        self.assertIn("unreadable hook payload", err.getvalue())


class StackFollowUpBase(unittest.TestCase):
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


class TestStackFollowUpState(StackFollowUpBase):
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
            self.assertIsNotNone(detect.read_pending(repo, now=1000.0 + detect.PENDING_TTL_SECONDS - 1))
            self.assertIsNone(detect.read_pending(repo, now=1000.0 + detect.PENDING_TTL_SECONDS + 1))

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
        with _repo_with_tool() as repo:
            detect.mark_pending(repo)
            self.assertFalse(
                os.path.abspath(detect.pending_state_path(repo)).startswith(os.path.abspath(repo))
            )


class TestStackFollowUpHook(StackFollowUpBase):
    def test_first_stack_push_reminds_and_arms_pending(self):
        with _repo_with_tool() as repo:
            advised, err = _run(STACK_PUSH_CMD, repo)
            self.assertTrue(advised)
            self.assertIn("create-pr.mjs", err)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_dry_run_arms_nothing_and_says_nothing(self):
        with _repo_with_tool() as repo:
            self.assertEqual(_run("mergify stack push --dry-run", repo), (False, ""))
            self.assertIsNone(detect.read_pending(repo))

    def test_real_push_after_a_dry_run_in_one_command_still_arms(self):
        with _repo_with_tool() as repo:
            self.assertTrue(_run("mergify stack push --dry-run && mergify stack push", repo)[0])
            self.assertIsNotNone(detect.read_pending(repo))

    def test_sanctioned_follow_up_clears_pending(self):
        with _repo_with_tool() as repo:
            _run(STACK_PUSH_CMD, repo)
            self.assertEqual(_run(FOLLOWUP_CMD, repo), (False, ""))
            self.assertIsNone(detect.read_pending(repo))

    def test_unrelated_command_while_pending_keeps_pending_and_is_silent(self):
        with _repo_with_tool() as repo:
            _run(STACK_PUSH_CMD, repo)
            self.assertEqual(_run("grep -r TODO .", repo), (False, ""))
            self.assertIsNotNone(detect.read_pending(repo))

    def test_malformed_state_reads_as_nothing_owed_on_second_push(self):
        with _repo_with_tool() as repo:
            _run(STACK_PUSH_CMD, repo)
            with open(detect.pending_state_path(repo), "w") as f:
                f.write("}{ truncated")
            _, err = _run(STACK_PUSH_CMD, repo)
            self.assertNotIn("has not run yet", err)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_expired_pending_reads_as_nothing_owed(self):
        with _repo_with_tool() as repo:
            detect.mark_pending(repo, now=time.time() - detect.PENDING_TTL_SECONDS - 60)
            _, err = _run(STACK_PUSH_CMD, repo)
            self.assertNotIn("has not run yet", err)

    def test_repo_without_create_pr_tool_never_arms_pending(self):
        with _repo_without_tool() as repo:
            _run(STACK_PUSH_CMD, repo)
            self.assertIsNone(detect.read_pending(repo))

    def test_pending_in_one_repo_does_not_leak_into_another(self):
        with _repo_with_tool() as one, _repo_with_tool() as two:
            _run(STACK_PUSH_CMD, one)
            _, err = _run(STACK_PUSH_CMD, two)
            self.assertNotIn("has not run yet", err)

    def test_unchecked_direct_writer_does_not_clear_pending(self):
        with _repo_with_tool() as repo:
            _run(STACK_PUSH_CMD, repo)
            _run(GH_PR_CREATE_CMD, repo)
            self.assertIsNotNone(detect.read_pending(repo))


if __name__ == "__main__":
    unittest.main()
