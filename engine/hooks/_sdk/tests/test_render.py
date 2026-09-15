import json
import unittest

from engine.hooks._sdk.finding import Finding
from engine.hooks._sdk.render import render_response


FINDING = Finding("rule.one", "subject", "stop here", "because")


class RenderTests(unittest.TestCase):
    def parse_stdout(self, rendered):
        stdout, stderr, code = rendered
        self.assertEqual(stderr, "")
        self.assertEqual(code, 0)
        return json.loads(stdout)

    def test_off_and_no_findings_are_silent(self):
        self.assertEqual(render_response("claude", "Stop", "off", [FINDING]), ("", "", 0))
        self.assertEqual(render_response("codex", "PreToolUse", "stop", []), ("", "", 0))

    def test_claude_stop_on_stop_and_pretooluse_blocks_with_stderr_exit_2(self):
        for event_name in ("Stop", "PreToolUse"):
            with self.subTest(event_name=event_name):
                stdout, stderr, code = render_response("claude", event_name, "stop", [FINDING])
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "stop here\n")
                self.assertEqual(code, 2)

    def test_claude_stop_on_other_event_uses_decision_block(self):
        data = self.parse_stdout(render_response("claude", "PostToolUse", "stop", [FINDING]))
        self.assertEqual(data["decision"], "block")
        self.assertEqual(data["reason"], "stop here")
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], "stop here")

    def test_claude_warn_uses_hook_specific_additional_context(self):
        data = self.parse_stdout(render_response("claude", "UserPromptSubmit", "warn", [FINDING]))
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], "stop here")

    def test_cursor_stop_uses_permission_deny_with_message(self):
        data = self.parse_stdout(render_response("cursor", "preToolUse", "stop", [FINDING]))
        self.assertEqual(data["permission"], "deny")
        self.assertEqual(data["user_message"], "stop here")

    def test_cursor_warn_uses_additional_context(self):
        data = self.parse_stdout(render_response("cursor", "postToolUse", "warn", [FINDING]))
        self.assertEqual(data["additional_context"], "stop here")

    def test_codex_pretool_stop_uses_permission_decision_deny(self):
        data = self.parse_stdout(render_response("codex", "PreToolUse", "stop", [FINDING]))
        output = data["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertEqual(output["permissionDecisionReason"], "stop here")

    def test_codex_other_stop_uses_decision_block(self):
        data = self.parse_stdout(render_response("codex", "PostToolUse", "stop", [FINDING]))
        self.assertEqual(data["decision"], "block")
        self.assertEqual(data["reason"], "stop here")
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], "stop here")

    def test_codex_warn_uses_hook_specific_additional_context(self):
        data = self.parse_stdout(render_response("codex", "Stop", "warn", [FINDING]))
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], "stop here")

    def test_multiple_findings_keep_one_message_per_line(self):
        other = Finding("rule.two", "subject-2", "also stop", "more")
        _stdout, stderr, code = render_response("claude", "Stop", "stop", [FINDING, other])
        self.assertEqual(stderr, "stop here\nalso stop\n")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
