#!/usr/bin/env python3
"""Tests for repeat-error-stop. Run: python3 -m unittest discover -s engine/hooks/repeat-error-stop/tests -v"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_posttooluse  # noqa: E402
import claude_pretooluse  # noqa: E402
import codex_posttooluse  # noqa: E402
import codex_pretooluse  # noqa: E402
import cursor_post_tool_use  # noqa: E402
import cursor_pretool  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402
import install_codex_hook  # noqa: E402
import install_cursor_hook  # noqa: E402

TIMEOUT = 'Error: Task "{name}" did not reach status "completed" within 55000ms\n  at waitFor (packages/app/e2e/helpers.ts:88:11)'
PASS = "✓ 15 tests passed\n0 failures\n"


def bash_payload(command: str, error: str, session: str = "s1") -> dict:
    """Shape of a real Claude Code PostToolUseFailure payload (captured 2026-09-01)."""
    return {
        "session_id": session,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": f"Exit code 1\n{error}",
        "is_interrupt": False,
    }


def success_payload(command: str, stdout: str, session: str = "s1") -> dict:
    """Shape of a real Claude Code PostToolUse payload; only fires on success."""
    return {
        "session_id": session,
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False},
    }


class StateDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(detect, "STATE_DIR", self._tmp.name)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class TestDetector(StateDirMixin, unittest.TestCase):
    def test_third_identical_error_blocks(self):
        for _ in range(2):
            kind, _reason = detect.record_result(bash_payload("pnpm test e2e", TIMEOUT.format(name="alpha")))
            self.assertEqual(kind, "none")
        kind, reason = detect.record_result(bash_payload("pnpm test e2e", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "block")
        self.assertIn("3 times", reason)
        self.assertIn("did not reach status", reason)

    def test_varying_quoted_names_still_trigger_block(self):
        for name in ("alpha", "beta", "gamma"):
            kind, _ = detect.record_result(bash_payload(f"pnpm test e2e -- {name}", TIMEOUT.format(name=name)))
        self.assertEqual(kind, "block")

    def test_two_identical_errors_stay_silent(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        self.assertEqual(kind, "none")

    def test_different_errors_do_not_trigger(self):
        errors = ["Error: ENOENT no such file", "fatal: not a git repository", "CONFLICT (content): merge conflict in x.ts"]
        for text in errors:
            kind, _ = detect.record_result(bash_payload("git x", text))
        self.assertEqual(kind, "none")

    def test_successful_output_never_counts(self):
        for _ in range(5):
            kind, _ = detect.record_result(success_payload("pnpm test", PASS))
        self.assertEqual(kind, "none")
        self.assertEqual(detect.load_state({"session_id": "s1"}), {})

    def test_success_output_containing_error_words_never_counts(self):
        noisy = "✓ merge-conflict-error.test.ts (5 tests)\nℹ fail 0\nPASS stack-branch log-remote-cmd-failure"
        for _ in range(5):
            kind, _ = detect.record_result(success_payload("pnpm test", noisy))
        self.assertEqual(kind, "none")

    def test_user_interrupt_is_ignored_no_hit(self):
        payload = bash_payload("pnpm test", "Error: boom")
        payload["is_interrupt"] = True
        for _ in range(5):
            kind, _ = detect.record_result(payload)
        self.assertEqual(kind, "none")

    def test_bare_exit_code_is_keyed_by_command_no_hit(self):
        detect.record_result({"hook_event_name": "PostToolUseFailure", "session_id": "s1", "tool_name": "Bash",
                              "tool_input": {"command": "grep -n foo a.ts"}, "error": "Exit code 1"})
        detect.record_result({"hook_event_name": "PostToolUseFailure", "session_id": "s1", "tool_name": "Bash",
                              "tool_input": {"command": "grep -n bar b.ts"}, "error": "Exit code 1"})
        kind, _ = detect.record_result({"hook_event_name": "PostToolUseFailure", "session_id": "s1", "tool_name": "Bash",
                                        "tool_input": {"command": "test -f c.ts"}, "error": "Exit code 1"})
        self.assertEqual(kind, "none")

    def test_edit_between_identical_failures_restarts_count_no_hit(self):
        detect.record_result(bash_payload("node validate.mjs", "PR body validation failed:"))
        detect.record_result(bash_payload("node validate.mjs", "PR body validation failed:"))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/body.md"}, "tool_response": "ok"})
        kind, _ = detect.record_result(bash_payload("node validate.mjs", "PR body validation failed:"))
        self.assertEqual(kind, "nudge")

    def test_blind_rerun_without_edit_triggers(self):
        for _ in range(2):
            detect.record_result(bash_payload("node validate.mjs", "PR body validation failed:"))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "cat /tmp/body.md"}, "tool_response": "text"})
        kind, _ = detect.record_result(bash_payload("node validate.mjs", "PR body validation failed:"))
        self.assertEqual(kind, "block")

    def test_observed_error_in_exit_zero_output_triggers(self):
        tail = "[1/7] e2e/restart.spec.ts\n" + TIMEOUT.format(name="alpha")
        for _ in range(3):
            kind, _ = detect.record_result(success_payload("tail -20 /tmp/e2e.log", tail))
        self.assertEqual(kind, "block")

    def test_echoed_source_code_with_throw_new_error_is_silent(self):
        for _ in range(4):
            kind, _ = detect.record_result(success_payload("grep -n Error src/x.ts", "12:    throw new Error(message);"))
        self.assertEqual(kind, "none")

    def test_cursor_style_result_with_exit_code_text_triggers(self):
        payload = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "pnpm test"},
                   "tool_response": "Exit code 1\nError: ENOENT: no such file or directory, open 'x'"}
        for _ in range(3):
            kind, _ = detect.record_result(payload)
        self.assertEqual(kind, "block")

    def test_sessions_are_isolated_no_hit(self):
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a"), session="one"))
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a"), session="one"))
        kind, _ = detect.record_result(bash_payload("x", TIMEOUT.format(name="a"), session="two"))
        self.assertEqual(kind, "none")

    def test_human_prompt_resets_and_stays_silent(self):
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        self.assertTrue(detect.handle_prompt({"session_id": "s1", "prompt": "ok try a different approach"}))
        kind, _ = detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        self.assertEqual(kind, "none")

    def test_loop_and_notification_prompts_do_not_reset(self):
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        self.assertFalse(detect.handle_prompt({"session_id": "s1", "prompt": "<command-name>/loop</command-name> babysit"}))
        self.assertFalse(detect.handle_prompt({"session_id": "s1", "prompt": "<task-notification><task-id>x</task-id>"}))
        kind, _ = detect.record_result(bash_payload("x", TIMEOUT.format(name="a")))
        self.assertEqual(kind, "block")

    def test_same_signature_after_successful_edit_triggers_nudge(self):
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "none")
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        kind, reason = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "nudge")
        self.assertIn("survived 1 edit(s)", reason)
        self.assertIn("did not reach status", reason)

    def test_same_signature_three_times_without_edit_blocks_and_never_nudges(self):
        seen = []
        for _ in range(3):
            kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
            seen.append(kind)
        self.assertEqual(seen, ["none", "none", "block"])

    def test_two_different_signatures_across_edit_stay_silent(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        kind, _ = detect.record_result(bash_payload("git status", "fatal: not a git repository"))
        self.assertEqual(kind, "none")

    def test_nudge_fires_once_and_third_epoch_stays_silent(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "nudge")
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "none")

    def test_repeat_error_stop_epochs_zero_disables_nudge(self):
        with patch.object(detect, "EPOCHS", 0):
            detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
            detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                                  "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
            kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "none")

    def test_malformed_state_file_fails_open_without_nudge(self):
        with open(detect.state_path({"session_id": "s1"}), "w") as handle:
            handle.write("{")
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "none")

    def test_wrong_typed_state_file_fails_open_without_nudge(self):
        with open(detect.state_path({"session_id": "s1"}), "w") as handle:
            json.dump({"errors": [], "blocked": [], "edit_epoch": []}, handle)
        kind, _ = detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="alpha")))
        self.assertEqual(kind, "none")
        blocked, _ = detect.tool_block_reason(bash_payload("pnpm test", ""))
        self.assertFalse(blocked)


class TestPreToolDeny(StateDirMixin, unittest.TestCase):
    def _arm(self):
        for _ in range(3):
            detect.record_result(bash_payload("cd /tmp/wt && pnpm test e2e", TIMEOUT.format(name="a")))

    def test_pretool_denies_rerun_of_failing_command(self):
        self._arm()
        blocked, reason = detect.tool_block_reason(bash_payload("cd /tmp/wt  &&  pnpm test e2e", ""))
        self.assertTrue(blocked)
        self.assertIn("denied", reason)

    def test_pretool_allows_unrelated_command(self):
        self._arm()
        blocked, _ = detect.tool_block_reason(bash_payload("git status", ""))
        self.assertFalse(blocked)

    def test_pretool_allows_everything_before_threshold_no_hit(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        blocked, _ = detect.tool_block_reason(bash_payload("pnpm test", ""))
        self.assertFalse(blocked)

    def test_claude_pretool_blocks_with_exit_two(self):
        self._arm()
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("cd /tmp/wt && pnpm test e2e", "")))):
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    claude_pretooluse.main()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("repeat-error-stop", err.getvalue())

    def test_codex_pretool_denies_with_native_decision(self):
        self._arm()
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("cd /tmp/wt && pnpm test e2e", "")))):
            with redirect_stdout(out):
                codex_pretooluse.main()
        data = json.loads(out.getvalue())
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_cursor_pretool_blocks(self):
        self._arm()
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("cd /tmp/wt && pnpm test e2e", "")))):
            with redirect_stdout(out):
                cursor_pretool.main()
        self.assertFalse(json.loads(out.getvalue())["continue"])

    def test_claude_posttool_emits_block_decision(self):
        out = io.StringIO()
        for _ in range(3):
            out = io.StringIO()
            with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("pnpm test", TIMEOUT.format(name="a"))))):
                with redirect_stdout(out):
                    claude_posttooluse.main()
        self.assertEqual(json.loads(out.getvalue())["decision"], "block")

    def test_claude_posttool_emits_nudge_additional_context_without_block_decision(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("pnpm test", TIMEOUT.format(name="a"))))):
            with redirect_stdout(out):
                claude_posttooluse.main()
        data = json.loads(out.getvalue())
        self.assertNotIn("decision", data)
        self.assertIn("survived 1 edit(s)", data["hookSpecificOutput"]["additionalContext"])

    def test_cursor_posttool_emits_nudge_additional_context(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("pnpm test", TIMEOUT.format(name="a"))))):
            with redirect_stdout(out):
                cursor_post_tool_use.main()
        self.assertIn("survived 1 edit(s)", json.loads(out.getvalue())["additional_context"])

    def test_codex_posttool_emits_nudge_additional_context(self):
        detect.record_result(bash_payload("pnpm test", TIMEOUT.format(name="a")))
        detect.record_result({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "/tmp/app.ts"}, "tool_response": "ok"})
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(bash_payload("pnpm test", TIMEOUT.format(name="a"))))):
            with redirect_stdout(out):
                codex_posttooluse.main()
        data = json.loads(out.getvalue())
        self.assertNotIn("decision", data)
        self.assertIn("survived 1 edit(s)", data["hookSpecificOutput"]["additionalContext"])

    def test_claude_posttool_success_payload_prints_nothing(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(success_payload("pnpm test", PASS)))):
            with redirect_stdout(out):
                claude_posttooluse.main()
        self.assertEqual(out.getvalue(), "")

    def test_malformed_stdin_fails_open(self):
        with patch.object(sys, "stdin", io.StringIO("not json")):
            claude_posttooluse.main()
            claude_pretooluse.main()


class TestInstallers(unittest.TestCase):
    def test_claude_installer_merges_once(self):
        base = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "other"}]}]}}
        once = install_claude_hook.merge_hooks(base)
        twice = install_claude_hook.merge_hooks(once)
        self.assertEqual(once, twice)
        self.assertEqual(len(once["hooks"]["Stop"]), 1)
        self.assertEqual(len(once["hooks"]["PostToolUseFailure"]), 1)
        self.assertEqual(len(once["hooks"]["PostToolUse"]), 1)
        self.assertIn("claude_pretooluse.py", once["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_claude_installer_replaces_stale_entry_not_duplicates(self):
        stale = {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                 "command": "python3 $HOME/.claude/hooks/repeat-error-stop/claude_posttooluse.py"}]}]}}
        merged = install_claude_hook.merge_hooks(stale)
        self.assertEqual(len(merged["hooks"]["PostToolUse"]), 1)
        self.assertIn("NotebookEdit", merged["hooks"]["PostToolUse"][0]["matcher"])

    def test_codex_installer_merges_once(self):
        once = install_codex_hook.merge_hooks({})
        twice = install_codex_hook.merge_hooks(once)
        self.assertEqual(once, twice)
        self.assertEqual(len(once["hooks"]["PreToolUse"]), 1)

    def test_cursor_installer_merges_once(self):
        base = {"version": 1, "hooks": {"stop": [{"command": "other"}]}}
        once = install_cursor_hook.merge_hooks(base)
        twice = install_cursor_hook.merge_hooks(once)
        self.assertEqual(once, twice)
        self.assertEqual(len(once["hooks"]["stop"]), 1)
        self.assertEqual(len(once["hooks"]["postToolUse"]), 1)


if __name__ == "__main__":
    unittest.main()
