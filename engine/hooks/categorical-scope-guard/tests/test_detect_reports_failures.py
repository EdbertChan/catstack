"""The detector fails closed AND says why when classification blows up.

Returning only an UNCHECKED finding would hide the cause: the finding text
reaches the model, but the traceback reaches nobody. Same stderr shape as the
other hooks (`catstack-hook-error <hook>: <Type>: <msg>`), so one grep finds
every hook failure in a session log.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
if HOOK_DIR not in sys.path:
    sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402

EVENT = {
    "tool_name": "Bash",
    "hook_event_name": "PreToolUse",
    "tool_input": {"command": "update tasks set status='queued' where status='pending'"},
}


class TestDetectorFailureIsReported(unittest.TestCase):
    def test_classifier_blowup_blocks_and_logs_to_stderr(self) -> None:
        err = io.StringIO()
        with patch.object(detect, "decide_payload", side_effect=RuntimeError("boom")):
            with redirect_stderr(err):
                findings = detect.detect(dict(EVENT))

        self.assertEqual(1, len(findings))
        self.assertEqual(detect.RULE_UNCHECKED, findings[0].rule_id)
        self.assertIn("UNCHECKED", findings[0].message)
        self.assertEqual(
            "catstack-hook-error categorical-scope-guard: RuntimeError: boom\n",
            err.getvalue(),
        )

    def test_non_shell_tool_stays_silent_and_logs_nothing(self) -> None:
        err = io.StringIO()
        with patch.object(detect, "decide_payload", side_effect=RuntimeError("boom")):
            with redirect_stderr(err):
                findings = detect.detect({"tool_name": "Read", "tool_input": {"file_path": "a.txt"}})

        self.assertEqual([], findings)
        self.assertEqual("", err.getvalue())


if __name__ == "__main__":
    unittest.main()
