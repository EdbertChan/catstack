from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest


SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

from finding import Finding  # noqa: E402
import modes  # noqa: E402
import render  # noqa: E402


def finding() -> Finding:
    return Finding("demo.rule", "/tmp/file.py", "Stop doing the risky thing.", "line 12")


class RenderTest(unittest.TestCase):
    def test_claude_stop_on_stop_uses_stderr_and_exit_2(self) -> None:
        stdout, stderr, code = render.render_response("claude", "Stop", "stop", [finding()])
        self.assertEqual("", stdout)
        self.assertEqual(2, code)
        self.assertIn("Stop doing the risky thing.", stderr)
        self.assertIn("Evidence: line 12", stderr)

    def test_claude_stop_on_pretooluse_uses_stderr_and_exit_2(self) -> None:
        stdout, stderr, code = render.render_response("claude", "PreToolUse", "stop", [finding()])
        self.assertEqual("", stdout)
        self.assertEqual(2, code)
        self.assertIn("Stop doing the risky thing.", stderr)

    def test_claude_warn_uses_hook_specific_additional_context(self) -> None:
        stdout, stderr, code = render.render_response("claude", "UserPromptSubmit", "warn", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        body = json.loads(stdout)
        self.assertEqual(
            {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "Stop doing the risky thing.\nEvidence: line 12",
            },
            body["hookSpecificOutput"],
        )

    def test_cursor_stop_uses_permission_deny(self) -> None:
        stdout, stderr, code = render.render_response("cursor", "preToolUse", "stop", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        body = json.loads(stdout)
        self.assertEqual("deny", body["permission"])
        self.assertIn("Stop doing the risky thing.", body["user_message"])

    def test_cursor_warn_uses_additional_context(self) -> None:
        stdout, stderr, code = render.render_response("cursor", "postToolUse", "warn", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        self.assertEqual(
            {"additional_context": "Stop doing the risky thing.\nEvidence: line 12"},
            json.loads(stdout),
        )

    def test_codex_pretool_stop_uses_permission_decision(self) -> None:
        stdout, stderr, code = render.render_response("codex", "PreToolUse", "stop", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        output = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("Stop doing the risky thing.", output["permissionDecisionReason"])

    def test_codex_non_pretool_stop_uses_decision_block(self) -> None:
        stdout, stderr, code = render.render_response("codex", "Stop", "stop", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        body = json.loads(stdout)
        self.assertEqual("block", body["decision"])
        self.assertEqual("Stop", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("Stop doing the risky thing.", body["reason"])

    def test_codex_warn_uses_hook_specific_additional_context(self) -> None:
        stdout, stderr, code = render.render_response("codex", "Stop", "warn", [finding()])
        self.assertEqual("", stderr)
        self.assertEqual(0, code)
        body = json.loads(stdout)
        self.assertEqual("Stop", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("Stop doing the risky thing.", body["hookSpecificOutput"]["additionalContext"])

    def test_off_and_no_findings_are_silent(self) -> None:
        self.assertEqual(("", "", 0), render.render_response("claude", "Stop", "off", [finding()]))
        self.assertEqual(("", "", 0), render.render_response("codex", "Stop", "stop", []))

    def test_mode_override_wins_over_registry(self) -> None:
        old = dict(os.environ)
        try:
            os.environ["CATSTACK_HOOK_MODE_DIU_STOP"] = "warn"
            self.assertEqual(("warn", "override"), modes.effective_mode("diu-stop", {}))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_registry_mode_is_used_without_override(self) -> None:
        old = dict(os.environ)
        try:
            os.environ.pop("CATSTACK_HOOK_MODE_DIU_STOP", None)
            self.assertEqual(("stop", "registry"), modes.effective_mode("diu-stop", {}))
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
