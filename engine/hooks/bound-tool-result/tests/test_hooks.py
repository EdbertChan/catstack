#!/usr/bin/env python3
"""Unit tests for bound-tool-result PreToolUse rewrite.

Run: python3 -m unittest discover -s engine/hooks/bound-tool-result/tests -v
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HOOK_DIR.parents[2]
HELPER = REPO_ROOT.joinpath("corpus", "skills", "principle-guard-the-context-window", "scripts", "capture_tool_result.py")
sys.path.insert(0, str(HOOK_DIR))

import claude_pre_tool_use  # noqa: E402
import codex_pre_tool_use  # noqa: E402
import cursor_pre_tool_use  # noqa: E402
import detect  # noqa: E402


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def shell_payload(command: str) -> dict:
    return {"tool_name": "Shell", "tool_input": {"command": command}}


def run_adapter(module, payload: dict) -> tuple[int, dict]:
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with patch.object(sys, "stdout", out):
            code = module.main()
    return code, json.loads(out.getvalue())


class TestDetectRewrite(unittest.TestCase):
    def test_rewrite_wraps_bash_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "capture_tool_result.py"
            helper.write_text("print('helper')\n", encoding="utf-8")
            decision = detect.decide(
                bash_payload("printf hi"),
                environ={"CATSTACK_CAPTURE_HELPER": str(helper), "HOME": tmp},
            )
        self.assertEqual(decision["outcome"], "rewrite")
        self.assertIn("capture_tool_result.py", decision["wrapped_command"])
        self.assertIn("printf hi", decision["wrapped_command"])
        self.assertNotIn("FAIL", decision["wrapped_command"])
        self.assertNotIn("Traceback", decision["wrapped_command"])

    def test_deny_when_helper_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            decision = detect.decide(
                bash_payload("printf hi"),
                home=tmp,
                environ={"HOME": tmp, "CATSTACK_CAPTURE_HELPER": str(Path(tmp) / "nope.py")},
            )
        self.assertEqual(decision["outcome"], "deny")
        self.assertIn("missing", decision["reason"].lower())

    def test_unrelated_edit_is_ignored(self):
        decision = detect.decide(
            {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "new_string": "x"}}
        )
        self.assertEqual(decision["outcome"], "unrelated")

    def test_already_wrapped_is_ignored(self):
        cmd = f"python3 {HELPER} -- printf hi"
        decision = detect.decide(bash_payload(cmd), environ={"CATSTACK_CAPTURE_HELPER": str(HELPER)})
        self.assertEqual(decision["outcome"], "already_wrapped")

    def test_shell_tool_name_rewrites(self):
        decision = detect.decide(
            shell_payload("ls"),
            environ={"CATSTACK_CAPTURE_HELPER": str(HELPER)},
        )
        self.assertEqual(decision["outcome"], "rewrite")


class TestAdapters(unittest.TestCase):
    def test_claude_emits_updated_input_on_rewrite(self):
        with patch.dict(os.environ, {"CATSTACK_CAPTURE_HELPER": str(HELPER)}, clear=False):
            code, reply = run_adapter(claude_pre_tool_use, bash_payload("echo ok"))
        self.assertEqual(code, 0)
        self.assertTrue(reply.get("continue"))
        self.assertIn("capture_tool_result.py", reply["updatedInput"]["command"])

    def test_cursor_emits_updated_input_on_rewrite(self):
        with patch.dict(os.environ, {"CATSTACK_CAPTURE_HELPER": str(HELPER)}, clear=False):
            code, reply = run_adapter(cursor_pre_tool_use, shell_payload("echo ok"))
        self.assertEqual(code, 0)
        self.assertEqual(reply.get("permission"), "allow")
        self.assertIn("capture_tool_result.py", reply["updated_input"]["command"])

    def test_codex_emits_updated_input_on_rewrite(self):
        with patch.dict(os.environ, {"CATSTACK_CAPTURE_HELPER": str(HELPER)}, clear=False):
            code, reply = run_adapter(codex_pre_tool_use, bash_payload("echo ok"))
        self.assertEqual(code, 0)
        output = reply["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "allow")
        self.assertIn("capture_tool_result.py", output["updatedInput"]["command"])

    def test_codex_is_silent_when_command_is_already_wrapped(self):
        payload = bash_payload(f"python3 {HELPER} -- echo ok")
        out = io.StringIO()
        with patch.dict(os.environ, {"CATSTACK_CAPTURE_HELPER": str(HELPER)}, clear=False):
            with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with patch.object(sys, "stdout", out):
                    code = codex_pre_tool_use.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")

    def test_codex_denies_with_pre_tool_use_permission_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "CATSTACK_CAPTURE_HELPER": str(Path(tmp) / "missing.py")}
            with patch.dict(os.environ, env, clear=True):
                code, reply = run_adapter(codex_pre_tool_use, bash_payload("echo ok"))
        self.assertEqual(code, 0)
        output = reply["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("missing", output["permissionDecisionReason"].lower())

    def test_claude_denies_when_helper_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "CATSTACK_CAPTURE_HELPER": str(Path(tmp) / "missing.py")}
            with patch.dict(os.environ, env, clear=True):
                code, reply = run_adapter(claude_pre_tool_use, bash_payload("echo ok"))
        self.assertEqual(code, 0)
        self.assertFalse(reply.get("continue"))
        self.assertEqual(reply.get("decision"), "block")


class TestUnreadableInput(unittest.TestCase):
    def _run_script(self, script_name: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOK_DIR / script_name)],
            input="{not-json",
            text=True,
            capture_output=True,
            check=False,
        )

    def test_claude_allows_unwrapped_on_bad_input(self):
        proc = self._run_script("claude_pre_tool_use.py")
        self.assertEqual(json.loads(proc.stdout), {"continue": True})
        self.assertTrue(proc.stderr)

    def test_codex_allows_unwrapped_on_bad_input(self):
        proc = self._run_script("codex_pre_tool_use.py")
        self.assertEqual(proc.stdout, "")
        self.assertTrue(proc.stderr)

    def test_cursor_allows_unwrapped_on_bad_input(self):
        proc = self._run_script("cursor_pre_tool_use.py")
        self.assertEqual(json.loads(proc.stdout), {"continue": True, "permission": "allow"})
        self.assertTrue(proc.stderr)


class TestNoPatternScan(unittest.TestCase):
    def test_detect_source_has_no_fail_or_traceback_classifier(self):
        source = (HOOK_DIR / "detect.py").read_text(encoding="utf-8")
        self.assertNotIn("STRUCTURAL_PATTERNS", source)
        self.assertNotIn("Traceback", source)
        lowered = source.lower()
        self.assertNotIn("fail-grep", lowered)
        self.assertNotIn("relevant lines", lowered)


if __name__ == "__main__":
    unittest.main()
