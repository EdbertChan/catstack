#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse_grep  # noqa: E402
import state  # noqa: E402


def blocking_grep_payload(session_id: str = "sdk-mode") -> dict[str, object]:
    return {
        "session_id": session_id,
        "hook_event_name": "PreToolUse",
        "tool_name": "Grep",
        "tool_input": {"pattern": "Draft not shown"},
    }


class SdkModeTest(unittest.TestCase):
    def test_warn_override_turns_current_stop_case_into_warning(self) -> None:
        payload = blocking_grep_payload()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as metrics:
            with patch.object(state, "STATE_DIR", tmp):
                state.remember_bug_complaint(
                    payload,
                    "We have a bug: \"Draft not shown\"",
                    ["Draft not shown"],
                    "checklist",
                )
                state.record_empty_grep(payload, "Draft not shown", "", "")
                state.record_empty_grep(payload, "Draft not shown", "", "")
                with patch.dict(
                    os.environ,
                    {
                        "CATSTACK_HOOK_MODE_BUG_COMPLAINT_LEAK": "warn",
                        "CATSTACK_HOOK_METRICS_DIR": metrics,
                    },
                    clear=False,
                ):
                    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                        with redirect_stdout(stdout), redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as caught:
                                claude_pretooluse_grep.main()

        self.assertEqual(0, caught.exception.code)
        self.assertEqual("", stderr.getvalue())
        body = json.loads(stdout.getvalue())
        self.assertIn("origin/master", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = blocking_grep_payload("sdk-events")
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as metrics:
            with patch.object(state, "STATE_DIR", tmp):
                state.remember_bug_complaint(
                    payload,
                    "We have a bug: \"Draft not shown\"",
                    ["Draft not shown"],
                    "checklist",
                )
                state.record_empty_grep(payload, "Draft not shown", "", "")
                state.record_empty_grep(payload, "Draft not shown", "", "")
                stored = state.load_state(payload)
                stored["last_grep_sig"] = state.grep_signature("Draft not shown", "", "")
                state.save_state(payload, stored)
                with patch.dict(
                    os.environ,
                    {
                        "CATSTACK_HOOK_MODE_BUG_COMPLAINT_LEAK": "warn",
                        "CATSTACK_HOOK_METRICS_DIR": metrics,
                    },
                    clear=False,
                ):
                    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                        with redirect_stdout(stdout):
                            with self.assertRaises(SystemExit) as caught:
                                claude_pretooluse_grep.main()

            self.assertEqual(0, caught.exception.code)
            today = datetime.now(timezone.utc).date().isoformat()
            rows = [
                json.loads(line)
                for line in (Path(metrics) / f"events-{today}.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            ["bug-complaint-leak.empty-grep", "bug-complaint-leak.repeat-grep"],
            sorted(row["rule_id"] for row in rows),
        )
        self.assertTrue(all(row["hook"] == "bug-complaint-leak" for row in rows))


if __name__ == "__main__":
    unittest.main()
