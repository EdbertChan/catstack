from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

from finding import Finding
from render import render


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = [
            Finding(
                rule_id="demo.rule",
                subject="tool:pytest",
                message="Stop and explain the repeated failure.",
                evidence="pytest failed three times",
            )
        ]

    def test_claude_stop_on_stop_event_uses_stderr_and_exit_2(self) -> None:
        stdout, stderr, code = render("claude", "Stop", "stop", self.findings)
        self.assertEqual("", stdout)
        self.assertEqual("Stop and explain the repeated failure.\n", stderr)
        self.assertEqual(2, code)

    def test_claude_stop_on_pretooluse_uses_stderr_and_exit_2(self) -> None:
        stdout, stderr, code = render("claude", "PreToolUse", "stop", self.findings)
        self.assertEqual("", stdout)
        self.assertIn("repeated failure", stderr)
        self.assertEqual(2, code)

    def test_claude_warn_uses_additional_context(self) -> None:
        stdout, stderr, code = render("claude", "UserPromptSubmit", "warn", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertEqual("UserPromptSubmit", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("repeated failure", body["hookSpecificOutput"]["additionalContext"])

    def test_claude_pretooluse_warn_keeps_stderr_empty_by_default(self) -> None:
        stdout, stderr, code = render("claude", "PreToolUse", "warn", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertIn("repeated failure", body["hookSpecificOutput"]["additionalContext"])

    def test_mirror_stderr_repeats_the_message_on_stderr(self) -> None:
        stdout, stderr, code = render("claude", "PreToolUse", "warn", self.findings, mirror_stderr=True)
        body = json.loads(stdout)
        self.assertEqual("Stop and explain the repeated failure.\n", stderr)
        self.assertEqual(0, code)
        self.assertIn("repeated failure", body["hookSpecificOutput"]["additionalContext"])

    def test_mirror_stderr_stays_silent_when_there_is_nothing_to_report(self) -> None:
        self.assertEqual(("", "", 0), render("claude", "PreToolUse", "warn", [], mirror_stderr=True))
        self.assertEqual(("", "", 0), render("claude", "PreToolUse", "off", self.findings, mirror_stderr=True))

    def test_mirror_stderr_does_not_double_report_a_stop(self) -> None:
        stdout, stderr, code = render("claude", "PreToolUse", "stop", self.findings, mirror_stderr=True)
        self.assertEqual("", stdout)
        self.assertEqual("Stop and explain the repeated failure.\n", stderr)
        self.assertEqual(2, code)

    def test_cursor_stop_uses_permission_deny_shape(self) -> None:
        stdout, stderr, code = render("cursor", "preToolUse", "stop", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertFalse(body["continue"])
        self.assertEqual("deny", body["permission"])
        self.assertIn("repeated failure", body["user_message"])

    def test_cursor_warn_uses_additional_context(self) -> None:
        stdout, stderr, code = render("cursor", "postToolUse", "warn", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertIn("repeated failure", body["additional_context"])

    def test_codex_stop_on_pretooluse_uses_permission_decision_deny(self) -> None:
        stdout, stderr, code = render("codex", "PreToolUse", "stop", self.findings)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("repeated failure", output["permissionDecisionReason"])

    def test_codex_stop_on_other_event_uses_block_decision(self) -> None:
        stdout, stderr, code = render("codex", "PostToolUse", "stop", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertEqual("block", body["decision"])
        self.assertIn("repeated failure", body["reason"])
        self.assertEqual("PostToolUse", body["hookSpecificOutput"]["hookEventName"])

    def test_codex_warn_uses_additional_context(self) -> None:
        stdout, stderr, code = render("codex", "UserPromptSubmit", "warn", self.findings)
        body = json.loads(stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertEqual("UserPromptSubmit", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("repeated failure", body["hookSpecificOutput"]["additionalContext"])

    def test_off_and_no_findings_are_silent_allows(self) -> None:
        self.assertEqual(("", "", 0), render("claude", "Stop", "off", self.findings))
        self.assertEqual(("", "", 0), render("cursor", "preToolUse", "warn", []))

    def test_multiple_findings_are_all_reported(self) -> None:
        findings = self.findings + [
            Finding("demo.second", "reply:1", "Name the second issue.", "second evidence")
        ]
        stdout, stderr, code = render("claude", "Stop", "stop", findings)
        self.assertEqual("", stdout)
        self.assertIn("Stop and explain", stderr)
        self.assertIn("Name the second issue", stderr)
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
