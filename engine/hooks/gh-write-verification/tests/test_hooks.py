"""End-to-end tests for gh-write-verification's three detectors.

Each detector gets a case that fires and a case that stays quiet, plus the
entrypoints exercised as real subprocesses so the exit-2 contract is proven,
not assumed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
sys.path.insert(0, HOOK_DIR)

from detect import (  # noqa: E402
    TRUST_PR_EDIT_ENV,
    broken_pr_edit,
    decide_stop,
    merges_missing_landing_proof,
    pretooluse_problems,
    silenced_mutations,
)

PRETOOLUSE = os.path.join(HOOK_DIR, "claude_pretooluse.py")
STOP_CHECK = os.path.join(HOOK_DIR, "claude_stop_check.py")

INCIDENT_RETARGET = 'gh pr edit "$1" --base main >/dev/null 2>&1'


def run_entrypoint(entrypoint: str, payload: dict, env_extra: dict | None = None):
    env = dict(os.environ)
    env.pop(TRUST_PR_EDIT_ENV, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, entrypoint],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "cwd": HOOK_DIR, "tool_input": {"command": command}}


def transcript(commands: list[str]) -> str:
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "land the stack"}})]
    for command in commands:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]},
        }))
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return handle.name


class TestBrokenPrEdit(unittest.TestCase):
    def test_every_flag_of_gh_pr_edit_is_blocked(self):
        for command in (
            "gh pr edit 295 --base main",
            "gh pr edit 295 --add-label admin-bypass",
            "gh pr edit 295 --title 'x'",
            "gh pr edit 295 --body-file /tmp/body.md",
        ):
            self.assertIsNotNone(broken_pr_edit(command), command)

    def test_block_message_names_the_gh_api_replacements(self):
        result = run_entrypoint(PRETOOLUSE, bash_payload("gh pr edit 295 --base main"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("gh api -X PATCH repos/<owner>/<repo>/pulls/<n>", result.stderr)
        self.assertIn("gh api -X POST repos/<owner>/<repo>/issues/<n>/labels", result.stderr)

    def test_the_sanctioned_gh_api_replacement_is_allowed(self):
        for command in (
            "gh api -X PATCH repos/EdbertChan/catstack/pulls/295 -f base=main",
            "gh api repos/EdbertChan/catstack/pulls/295 --jq .base.ref",
            "gh pr view 295 --json baseRefName",
        ):
            self.assertEqual(pretooluse_problems(command), [], command)

    def test_trust_env_lets_gh_pr_edit_through(self):
        result = run_entrypoint(
            PRETOOLUSE,
            bash_payload("gh pr edit 295 --base main"),
            {TRUST_PR_EDIT_ENV: "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class TestSilencedMutation(unittest.TestCase):
    def test_the_incident_line_is_flagged(self):
        self.assertEqual(silenced_mutations(INCIDENT_RETARGET), [INCIDENT_RETARGET])

    def test_mutations_with_both_streams_discarded_are_flagged(self):
        for command in (
            "git push origin HEAD >/dev/null 2>&1",
            "gh pr merge 291 --squash &>/dev/null",
            "gh api -X POST repos/o/r/issues/1/labels -f 'labels[]=x' > /dev/null 2>/dev/null",
            "git merge origin/main 2>/dev/null >/dev/null",
            "curl -X DELETE https://example.test/thing >/dev/null 2>&1",
        ):
            self.assertTrue(silenced_mutations(command), command)

    def test_read_only_commands_with_discarded_output_stay_silent(self):
        for command in (
            "grep -q needle haystack.txt 2>/dev/null",
            "command -v shellcheck >/dev/null 2>&1",
            "git cat-file -e abc123^{commit} 2>/dev/null",
            "git status --porcelain >/dev/null 2>&1",
            "gh pr view 295 --json state >/dev/null 2>&1",
            "pgrep -f run_all_tests >/dev/null 2>&1",
            "diff -q a b >/dev/null 2>&1",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_a_checked_exit_code_stays_silent(self):
        for command in (
            "git push origin HEAD >/dev/null 2>&1 || exit 1",
            "if ! git push origin HEAD >/dev/null 2>&1; then echo failed; fi",
            "git push origin HEAD >/dev/null 2>&1 && echo pushed",
            "set -euo pipefail\ngit push origin HEAD >/dev/null 2>&1",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_one_stream_left_visible_stays_silent(self):
        for command in (
            "git push origin HEAD >/dev/null",
            "git push origin HEAD 2>/dev/null",
            "git push origin HEAD 2>&1 >/dev/null",
        ):
            self.assertEqual(silenced_mutations(command), [], command)

    def test_a_redirect_belonging_to_an_earlier_command_stays_silent(self):
        command = "grep -q main .git/HEAD 2>/dev/null && git push origin HEAD"
        self.assertEqual(silenced_mutations(command), [])

    def test_a_file_write_mentioning_the_shape_is_allowed(self):
        payload = {
            "tool_name": "Write",
            "cwd": HOOK_DIR,
            "tool_input": {"file_path": "/tmp/notes.md", "content": INCIDENT_RETARGET},
        }
        result = run_entrypoint(PRETOOLUSE, payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_heredoc_written_script_is_flagged(self):
        command = "cat > retarget.sh <<'EOS'\ngh pr merge 291 --squash >/dev/null 2>&1\nEOS"
        self.assertTrue(silenced_mutations(command))

    def test_entrypoint_denies_a_discarded_mutation(self):
        result = run_entrypoint(PRETOOLUSE, bash_payload("git push origin HEAD >/dev/null 2>&1"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("discards both stdout and stderr", result.stderr)


class TestUnverifiedLanding(unittest.TestCase):
    def test_a_merge_with_no_landing_check_is_flagged(self):
        self.assertEqual(
            merges_missing_landing_proof(["gh pr merge 291 --squash --admin", "gh pr view 291"]),
            ["PR #291"],
        )

    def test_every_unproven_merge_in_the_turn_is_flagged(self):
        commands = [
            "gh pr merge 291 --squash",
            "gh pr merge 292 --squash",
            "bash verify_pr_landed_on_trunk.sh 292",
        ]
        self.assertEqual(merges_missing_landing_proof(commands), ["PR #291"])

    def test_a_verified_landing_stays_silent(self):
        for proof in (
            "bash verify_pr_landed_on_trunk.sh 291",
            "git merge-base --is-ancestor 314f0447 origin/main",
            "git branch -r --contains 314f0447",
        ):
            self.assertEqual(
                merges_missing_landing_proof(["gh pr merge 291 --squash", proof]), [], proof
            )

    def test_a_turn_with_no_merge_stays_silent(self):
        self.assertEqual(merges_missing_landing_proof(["git status", "gh pr view 291"]), [])

    def test_stop_entrypoint_denies_an_unproven_merge(self):
        path = transcript(["gh pr merge 291 --squash --admin"])
        try:
            result = run_entrypoint(STOP_CHECK, {"transcript_path": path})
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("verify_pr_landed_on_trunk.sh", result.stderr)
            self.assertIn("PR #291", result.stderr)
        finally:
            os.unlink(path)

    def test_stop_entrypoint_allows_a_proven_merge(self):
        path = transcript([
            "gh pr merge 291 --squash --admin",
            'bash "$HOME/.claude/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh" 291',
        ])
        try:
            result = run_entrypoint(STOP_CHECK, {"transcript_path": path})
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            os.unlink(path)

    def test_a_missing_transcript_fails_open(self):
        self.assertIsNone(decide_stop({"transcript_path": "/nonexistent/transcript.jsonl"}))
        self.assertIsNone(decide_stop({}))

    def test_a_malformed_transcript_line_is_ignored(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        handle.write("not json at all\n{\n")
        handle.close()
        try:
            self.assertIsNone(decide_stop({"transcript_path": handle.name}))
        finally:
            os.unlink(handle.name)

    def test_stop_hook_active_stays_silent(self):
        path = transcript(["gh pr merge 291 --squash --admin"])
        try:
            self.assertIsNone(decide_stop({"transcript_path": path, "stop_hook_active": True}))
        finally:
            os.unlink(path)


class TestVerificationScript(unittest.TestCase):
    def test_the_script_refuses_a_call_with_no_pr_number(self):
        script = os.path.join(HOOK_DIR, "verify_pr_landed_on_trunk.sh")
        result = subprocess.run(["bash", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertIn("usage:", result.stderr)

    def test_the_script_parses_as_valid_bash(self):
        script = os.path.join(HOOK_DIR, "verify_pr_landed_on_trunk.sh")
        result = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
