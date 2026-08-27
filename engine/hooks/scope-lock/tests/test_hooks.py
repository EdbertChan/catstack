#!/usr/bin/env python3
"""Regression tests for the per-session scope-lock hook."""
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
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretool_scope  # noqa: E402
import claude_prompt_scope  # noqa: E402
import codex_pretool_scope  # noqa: E402
import codex_prompt_scope  # noqa: E402
import cursor_before_submit  # noqa: E402
import cursor_pretool_scope  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402
import install_codex_hook  # noqa: E402
import install_cursor_hook  # noqa: E402


def fixture_messages(name: str) -> list[str]:
    messages: list[str] = []
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("type") != "user":
                continue
            messages.append(row["message"]["content"])
    return messages


def append_assistant(path: str, text: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }) + "\n")


def run_main(main, payload: dict) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class ScopeLockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        detect.STATE_DIR = self.tmp.name
        self.transcript = os.path.join(self.tmp.name, "session.jsonl")
        open(self.transcript, "w", encoding="utf-8").close()
        self.base = {"session_id": "session-1", "transcript_path": self.transcript}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prompt(self, text: str) -> dict:
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": text},
            }) + "\n")
        return detect.process_prompt({**self.base, "prompt": text})

    def tool(self, name: str = "Bash") -> tuple[bool, str]:
        return detect.tool_block_reason({**self.base, "tool_name": name})


class TestDetection(ScopeLockCase):
    def test_repeated_drift_fixture_detects_same_class(self):
        messages = fixture_messages("repeated_drift.jsonl")
        self.assertEqual([detect.correction_class(m) for m in messages], ["scope", "scope"])

    def test_ordinary_product_confusion_does_not_trigger(self):
        [message] = fixture_messages("ordinary_product_confusion.jsonl")
        self.assertIsNone(detect.correction_class(message))

    def test_explicit_scope_expansion_does_not_trigger(self):
        [message] = fixture_messages("explicit_scope_expansion.jsonl")
        self.assertIsNone(detect.correction_class(message))


class TestStateMachine(ScopeLockCase):
    def test_repeated_drift_fixture_triggers_hard_stop(self):
        first, second = fixture_messages("repeated_drift.jsonl")
        self.prompt(first)
        append_assistant(self.transcript, "You're right. I will only fix it locally.")
        self.assertTrue(self.tool("Write")[0])
        result = self.prompt(second)
        self.assertEqual(result["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])

    def test_first_correction_blocks_mutating_and_external_tools(self):
        result = self.prompt("wtf are you doing? Just fix it locally.")
        self.assertEqual(result["phase"], "contract_required")
        for tool in ("Bash", "Write", "Edit", "WebFetch", "mcp__github__create_pull_request"):
            blocked, reason = self.tool(tool)
            self.assertTrue(blocked, tool)
            self.assertIn("SCOPE CONTRACT:", reason)

    def test_first_correction_allows_local_read_only_tools(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        for tool in ("Read", "Grep", "Glob", "LS"):
            blocked, _ = self.tool(tool)
            self.assertFalse(blocked, tool)

    def test_one_line_scope_contract_releases_first_gate_but_persists_lock(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "SCOPE CONTRACT: Change only local catstack hook files; do not touch DO1 or queues.")
        blocked, _ = self.tool("Write")
        self.assertFalse(blocked)
        state = detect.load_state(self.base)
        self.assertEqual(state["phase"], "locked")
        self.assertIn("local catstack", state["contract"].lower())

    def test_apology_and_plain_restatement_do_not_clear_first_gate(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "Sorry. I understand: I will only fix it locally.")
        blocked, _ = self.tool("Write")
        self.assertTrue(blocked)

    def test_second_same_class_correction_hard_stops_every_tool(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "SCOPE CONTRACT: Fix only local catstack support.")
        self.assertFalse(self.tool("Write")[0])
        result = self.prompt(
            "why did you expand into babysitting the merge queue? All I am asking is catstack support."
        )
        self.assertEqual(result["phase"], "hard_stop")
        append_assistant(self.transcript, "SCOPE CONTRACT: Sorry; catstack only.")
        for tool in ("Read", "Grep", "Bash", "Write", "WebFetch"):
            blocked, reason = self.tool(tool)
            self.assertTrue(blocked, tool)
            self.assertIn("/reflect", reason)
            self.assertIn("automate-me", reason)

    def test_reflect_without_automate_me_does_not_clear_hard_stop(self):
        self.prompt("what are you doing? just do this locally")
        self.prompt("you are drifting again; that is not what I asked")
        self.prompt("/reflect")
        self.assertTrue(self.tool("Read")[0])

    def test_reflect_and_automate_me_clear_hard_stop(self):
        self.prompt("what are you doing? just do this locally")
        self.prompt("you are drifting again; that is not what I asked")
        result = self.prompt("/reflect and automate-me this repeated scope drift")
        self.assertEqual(result["phase"], "reflection_acknowledged")
        self.assertFalse(self.tool("Read")[0])


class TestHarnessWrappers(ScopeLockCase):
    def test_claude_prompt_injects_scope_contract_instruction(self):
        payload = {**self.base, "prompt": "wtf are you doing? Just fix it locally."}
        code, out, _ = run_main(claude_prompt_scope.main, payload)
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertIn("SCOPE CONTRACT:", body["hookSpecificOutput"]["additionalContext"])

    def test_claude_pretool_blocks_with_exit_two(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, _, err = run_main(claude_pretool_scope.main, {**self.base, "tool_name": "Write"})
        self.assertEqual(code, 2)
        self.assertIn("SCOPE CONTRACT:", err)

    def test_cursor_before_submit_records_lock(self):
        payload = {**self.base, "prompt": "wtf are you doing? Just fix it locally."}
        code, out, _ = run_main(cursor_before_submit.main, payload)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"continue": True})
        self.assertEqual(detect.load_state(self.base)["phase"], "contract_required")

    def test_cursor_pretool_blocks(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, out, _ = run_main(cursor_pretool_scope.main, {**self.base, "tool_name": "Write"})
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertFalse(body["continue"])
        self.assertIn("SCOPE CONTRACT:", body["user_message"])

    def test_codex_prompt_injects_scope_contract_instruction(self):
        payload = {**self.base, "prompt": "wtf are you doing? Just fix it locally."}
        code, out, _ = run_main(codex_prompt_scope.main, payload)
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertIn("SCOPE CONTRACT:", body["hookSpecificOutput"]["additionalContext"])

    def test_codex_pretool_denies_with_native_decision(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, out, _ = run_main(codex_pretool_scope.main, {**self.base, "tool_name": "Bash"})
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("SCOPE CONTRACT:", decision["permissionDecisionReason"])


class TestInstallers(unittest.TestCase):
    def test_claude_installer_merges_prompt_and_pretool_once(self):
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": []}]}}
        merged = install_claude_hook.merge_hooks(settings)
        merged_twice = install_claude_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["Stop"]), 1)

    def test_cursor_installer_merges_prompt_and_pretool_once(self):
        hooks = {"version": 1, "hooks": {"stop": [{"type": "prompt", "prompt": "keep"}]}}
        merged = install_cursor_hook.merge_hooks(hooks)
        merged_twice = install_cursor_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["beforeSubmitPrompt"]), 1)
        self.assertEqual(len(merged["hooks"]["preToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["stop"]), 1)

    def test_codex_installer_merges_native_prompt_and_pretool_once(self):
        hooks = {"hooks": {"Stop": [{"hooks": []}]}}
        merged = install_codex_hook.merge_hooks(hooks)
        merged_twice = install_codex_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["Stop"]), 1)

    def test_codex_installer_migrates_legacy_pretool_without_dropping_it(self):
        legacy = {
            "pre_tool_use": [{
                "matcher": "exec",
                "hooks": [{"type": "command", "command": "python3 existing.py"}],
            }]
        }
        merged = install_codex_hook.merge_hooks(legacy)
        self.assertNotIn("pre_tool_use", merged)
        commands = [
            hook["command"]
            for entry in merged["hooks"]["PreToolUse"]
            for hook in entry["hooks"]
        ]
        self.assertIn("python3 existing.py", commands)
        self.assertEqual(merged["hooks"]["PreToolUse"][0]["matcher"], "Bash")


if __name__ == "__main__":
    unittest.main()
