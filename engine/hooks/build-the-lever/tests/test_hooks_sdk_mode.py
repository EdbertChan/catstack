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

import claude_prompt_submit  # noqa: E402
import cursor_post_tool_use  # noqa: E402
import detect  # noqa: E402
import state  # noqa: E402


BULK_RENAME = "rename this config key across 40 files, and update every call site that reads the old name."


def run_main(main, payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


class HooksSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state_tmp = tempfile.TemporaryDirectory()
        self.metrics_tmp = tempfile.TemporaryDirectory()
        detect.STATE_DIR = self.state_tmp.name
        state.STATE_DIR = self.state_tmp.name
        self.env = patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": self.metrics_tmp.name},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.metrics_tmp.cleanup()
        self.state_tmp.cleanup()

    def _fourth_edit_payload(self, session_id: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": session_id,
            "hook_event_name": "postToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "d.ts"},
        }
        for path in ("a.ts", "b.ts", "c.ts"):
            detect.record_file_mutation(payload, path)
        return payload

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_BUILD_THE_LEVER": "stop"}):
            stop_code, stop_out, stop_err = run_main(
                cursor_post_tool_use.main,
                self._fourth_edit_payload("sdk-stop"),
            )
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_BUILD_THE_LEVER": "warn"}):
            warn_code, warn_out, warn_err = run_main(
                cursor_post_tool_use.main,
                self._fourth_edit_payload("sdk-warn"),
            )

        self.assertEqual(0, stop_code)
        self.assertEqual("", stop_err)
        stopped = json.loads(stop_out)
        self.assertFalse(stopped["continue"])
        self.assertEqual("deny", stopped["permission"])
        self.assertIn("build-the-lever", stopped["user_message"])
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertNotIn("permission", warning)
        self.assertIn("build-the-lever", warning["additional_context"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = {
            "prompt": BULK_RENAME,
            "session_id": "sdk-events",
            "hook_event_name": "UserPromptSubmit",
        }
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_BUILD_THE_LEVER": "warn"}):
            code, out, err = run_main(claude_prompt_submit.main, payload)
            edit_code, edit_out, edit_err = run_main(
                cursor_post_tool_use.main,
                self._fourth_edit_payload("sdk-edit-events"),
            )

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.metrics_tmp.name) / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("build-the-lever", out)
        self.assertEqual(0, edit_code)
        self.assertEqual("", edit_err)
        self.assertIn("build-the-lever", edit_out)
        self.assertEqual(2, len(finding_rows))
        self.assertEqual(
            ["build-the-lever.bulk-prompt", "build-the-lever.many-file-edits"],
            sorted(row["rule_id"] for row in finding_rows),
        )
        self.assertTrue(all(row["hook"] == "build-the-lever" for row in finding_rows))
        self.assertTrue(all(row["mode"] == "warn" for row in finding_rows))
        self.assertTrue(all(row["mode_source"] == "override" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
