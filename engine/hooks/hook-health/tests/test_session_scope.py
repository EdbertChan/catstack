from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402


def row(session: str | None, outcome: str = "timed_out", hook: str = "hedge-runs-prove-it") -> dict:
    data = {"harness": "claude", "hook": hook, "script": "claude_stop_check.py",
            "outcome": outcome, "exit_code": 124, "stderr_tail": "timed out after 9.5s"}
    if session is not None:
        data["session_id"] = session
    return data


class SessionScopedFailures(unittest.TestCase):
    """The notice names failures from this session, not from any session."""

    def test_failure_in_this_session_fires(self) -> None:
        text = detect.notice([row("8e90eb8a-7030")], "claude", session="8e90eb8a-7030")
        self.assertIsNotNone(text)
        self.assertIn("hedge-runs-prove-it/claude_stop_check.py timed_out", text)

    def test_failure_from_another_session_stays_silent(self) -> None:
        rows = [row("other-session"), row("third-session", outcome="crashed")]
        self.assertIsNone(detect.notice(rows, "claude", session="8e90eb8a-7030"))

    def test_rows_with_no_session_id_are_not_counted_for_this_session(self) -> None:
        self.assertIsNone(detect.notice([row(None)], "claude", session="8e90eb8a-7030"))

    def test_only_this_sessions_failures_are_counted(self) -> None:
        rows = [row("mine"), row("other-session", hook="narrow-the-scope"), row("mine", hook="explicit-failures")]
        text = detect.notice(rows, "claude", session="mine")
        self.assertIn("2 hook run(s) failed", text)
        self.assertNotIn("narrow-the-scope", text)

    def test_payload_with_no_session_id_is_reported_unchecked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}), \
                patch.object(detect, "start_scan") as scan:
            findings = detect.detect({"hook_event_name": "UserPromptSubmit"})
        scan.assert_not_called()
        self.assertEqual([f.rule_id for f in findings], [detect.RULE_UNCHECKED_SESSION])
        self.assertIn("unchecked", findings[0].message)


if __name__ == "__main__":
    unittest.main()
