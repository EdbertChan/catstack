#!/usr/bin/env python3
"""pr-schema-gate never blocks: it checks PR text with the repo's own validator and advises.

The command literals are assembled at runtime; see COMMAND_LITERALS_ARE_SPLIT in test_hooks.py.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402

GH_PR = "gh pr "
STACK_PUSH_CMD = "mergify stack push"
FOLLOWUP_CMD = 'node scripts/create-pr.mjs --title "x" --base main --body-file /tmp/b.md --update-existing'

VALIDATOR_PASSES = 'console.log("PR body validation passed.");\n'
VALIDATOR_FAILS = (
    'console.error("- Missing required section: ## Test Plan");\n'
    'console.error("- Missing required section: ## Revert Plan");\n'
    "process.exit(1);\n"
)
VALIDATOR_CRASHES = 'console.error("Error: Cannot find module typescript");\nprocess.exit(3);\n'
VALIDATOR_HANGS = "setTimeout(() => {}, 60000);\n"


def _repo(validator_source: str | None) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    os.makedirs(os.path.join(tmp.name, "scripts"))
    os.makedirs(os.path.join(tmp.name, ".git"))
    with open(os.path.join(tmp.name, "scripts", "create-pr.mjs"), "w") as f:
        f.write("// stub\n")
    if validator_source is not None:
        with open(os.path.join(tmp.name, "scripts", "validate-pr-body.mjs"), "w") as f:
            f.write(validator_source)
    return tmp


def _body_file(directory: str, text: str = "## Summary\n\nhi\n") -> str:
    path = os.path.join(directory, "pr-body.md")
    with open(path, "w") as f:
        f.write(text)
    return path


class _stdin:
    def __init__(self, text: str):
        self._text = text
        self._old = None

    def __enter__(self):
        self._old = sys.stdin
        sys.stdin = io.StringIO(self._text)

    def __exit__(self, *exc):
        sys.stdin = self._old


def _run(command: str, cwd: str, tool_name: str = "Bash"):
    """Run the hook once; return (exit_code, stderr, additional_context)."""
    err, out = io.StringIO(), io.StringIO()
    code = 0
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}, "cwd": cwd})
    try:
        with redirect_stderr(err), redirect_stdout(out):
            with _stdin(payload):
                claude_pretooluse.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    context = ""
    if out.getvalue().strip():
        context = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    return code, err.getvalue(), context


class StateIsolated(unittest.TestCase):
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


@unittest.skipUnless(shutil.which("node"), "node is required to run the repo validator stub")
class TestDirectBodyWritesAreCheckedNotBlocked(StateIsolated):
    def test_real_blocked_payload_from_the_incident_is_allowed(self):
        with _repo(VALIDATOR_PASSES) as repo:
            body = _body_file(repo)
            command = (GH_PR + 'edit 12058 --title "[Review-unit checker](1) Show which words tripped '
                       'the checker, and stop counting file names (local)" --body-file ' + body)
            code, _, context = _run(command, repo)
            self.assertEqual(code, 0)
            self.assertEqual(context, "")

    def test_failing_body_file_is_allowed_and_lists_the_validator_errors(self):
        with _repo(VALIDATOR_FAILS) as repo:
            body = _body_file(repo)
            code, err, context = _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIn("Missing required section: ## Test Plan", context)
            self.assertIn("Missing required section: ## Revert Plan", context)
            self.assertIn("not blocked", context)
            self.assertIn("Missing required section: ## Test Plan", err)

    def test_pr_create_with_a_failing_body_file_is_allowed_and_advised(self):
        with _repo(VALIDATOR_FAILS) as repo:
            body = _body_file(repo)
            code, _, context = _run(GH_PR + "create --title x --base main --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIn("## Test Plan", context)

    def test_gh_api_patch_with_a_body_file_field_is_checked(self):
        with _repo(VALIDATOR_FAILS) as repo:
            body = _body_file(repo)
            command = "gh api -X PATCH repos/{owner}/{repo}/pulls/12058 -F body=@" + body
            code, _, context = _run(command, repo)
            self.assertEqual(code, 0)
            self.assertIn("## Revert Plan", context)

    def test_relative_body_file_resolves_against_the_command_directory(self):
        with _repo(VALIDATOR_FAILS) as repo:
            _body_file(repo)
            code, _, context = _run("cd " + repo + " && " + GH_PR + "edit 7 --body-file pr-body.md", repo)
            self.assertEqual(code, 0)
            self.assertIn("## Test Plan", context)

    def test_body_file_named_by_an_earlier_variable_is_checked(self):
        with _repo(VALIDATOR_FAILS) as repo:
            body = _body_file(repo)
            command = "B=" + body + "\n" + GH_PR + 'edit 7 --title "t" --body-file $B; echo "exit=$?"'
            code, _, context = _run(command, repo)
            self.assertEqual(code, 0)
            self.assertIn("## Test Plan", context)
            self.assertIn(body, context)

    def test_body_file_with_an_unresolved_variable_is_reported_as_unchecked(self):
        with _repo(VALIDATOR_PASSES) as repo:
            code, _, context = _run(GH_PR + "edit 7 --body-file $NEVER_SET_PR_BODY", repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("$NEVER_SET_PR_BODY", context)

    def test_validator_crash_is_reported_as_unchecked_not_clean(self):
        with _repo(VALIDATOR_CRASHES) as repo:
            body = _body_file(repo)
            code, _, context = _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("exit 3", context)

    def test_validator_timeout_is_reported_as_unchecked(self):
        original = detect.VALIDATOR_TIMEOUT_SECONDS
        detect.VALIDATOR_TIMEOUT_SECONDS = 0.5
        self.addCleanup(setattr, detect, "VALIDATOR_TIMEOUT_SECONDS", original)
        with _repo(VALIDATOR_HANGS) as repo:
            body = _body_file(repo)
            code, _, context = _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("timed out", context)

    def test_missing_body_file_is_reported_as_unchecked(self):
        with _repo(VALIDATOR_PASSES) as repo:
            missing = os.path.join(repo, "never-written.md")
            code, _, context = _run(GH_PR + "edit 7 --body-file " + missing, repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("not found", context)

    def test_unreadable_body_file_is_reported_as_unchecked(self):
        with _repo(VALIDATOR_PASSES) as repo:
            code, _, context = _run(GH_PR + "edit 7 --body-file " + repo, repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)

    def test_inline_body_is_allowed_and_reported_as_unchecked(self):
        with _repo(VALIDATOR_PASSES) as repo:
            code, _, context = _run(GH_PR + "edit 7 --body 'placeholder'", repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("inline", context)

    def test_repo_without_a_validator_is_reported_as_unchecked(self):
        with _repo(None) as repo:
            body = _body_file(repo)
            code, _, context = _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIn("could not check", context)
            self.assertIn("validate-pr-body.mjs", context)

    def test_non_claude_shell_gets_stderr_only(self):
        with _repo(VALIDATOR_FAILS) as repo:
            body = _body_file(repo)
            code, err, context = _run(GH_PR + "edit 7 --body-file " + body, repo, tool_name="exec_command")
            self.assertEqual(code, 0)
            self.assertEqual(context, "")
            self.assertIn("## Test Plan", err)


@unittest.skipUnless(shutil.which("node"), "node is required to run the repo validator stub")
class TestStackFollowUpIsARemindernotABlock(StateIsolated):
    def test_first_stack_push_is_allowed_and_names_the_follow_up(self):
        with _repo(VALIDATOR_PASSES) as repo:
            code, _, context = _run(STACK_PUSH_CMD, repo)
            self.assertEqual(code, 0)
            self.assertIn("create-pr.mjs", context)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_second_stack_push_while_pending_is_allowed_with_a_reminder(self):
        with _repo(VALIDATOR_PASSES) as repo:
            _run(STACK_PUSH_CMD, repo)
            code, _, context = _run(STACK_PUSH_CMD, repo)
            self.assertEqual(code, 0)
            self.assertIn("has not run yet", context)

    def test_clean_direct_body_write_clears_the_owed_follow_up(self):
        with _repo(VALIDATOR_PASSES) as repo:
            _run(STACK_PUSH_CMD, repo)
            body = _body_file(repo)
            code, _, _ = _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertEqual(code, 0)
            self.assertIsNone(detect.read_pending(repo))

    def test_failing_direct_body_write_keeps_the_owed_follow_up(self):
        with _repo(VALIDATOR_FAILS) as repo:
            _run(STACK_PUSH_CMD, repo)
            body = _body_file(repo)
            _run(GH_PR + "edit 7 --body-file " + body, repo)
            self.assertIsNotNone(detect.read_pending(repo))

    def test_sanctioned_follow_up_clears_pending_silently(self):
        with _repo(VALIDATOR_PASSES) as repo:
            _run(STACK_PUSH_CMD, repo)
            code, err, context = _run(FOLLOWUP_CMD, repo)
            self.assertEqual((code, err, context), (0, "", ""))
            self.assertIsNone(detect.read_pending(repo))


class TestNeighboursStaySilent(StateIsolated):
    def test_title_only_edit_is_silent(self):
        with _repo(VALIDATOR_FAILS) as repo:
            self.assertEqual(_run(GH_PR + "edit 7 --title 'new title'", repo), (0, "", ""))

    def test_gh_api_read_of_a_pull_is_silent(self):
        with _repo(VALIDATOR_FAILS) as repo:
            self.assertEqual(_run("gh api repos/o/r/pulls/7 --jq .body", repo), (0, "", ""))

    def test_create_pr_mjs_subprocess_shape_is_silent(self):
        with _repo(VALIDATOR_FAILS) as repo:
            self.assertEqual(_run("gh api repos/o/r/pulls --method POST --input -", repo), (0, "", ""))

    def test_repo_without_create_pr_tool_is_silent(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            self.assertEqual(_run(GH_PR + "edit 7 --body 'x'", repo), (0, "", ""))

    def test_heredoc_that_only_writes_the_text_is_silent(self):
        with _repo(VALIDATOR_FAILS) as repo:
            command = "cat > notes.md <<EOF\n" + GH_PR + "edit 7 --body x\nEOF"
            self.assertEqual(_run(command, repo), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
