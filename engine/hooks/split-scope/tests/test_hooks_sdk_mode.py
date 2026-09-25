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

import cursor_before_submit  # noqa: E402
import cursor_post_tool_use  # noqa: E402
import state  # noqa: E402


PROMPT = "Please plan multiple PRs for this refactor."


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
        self.registry_tmp = tempfile.TemporaryDirectory()
        state.STATE_DIR = self.state_tmp.name
        self.registry_path = self._registry("stop")
        self.env = patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": self.metrics_tmp.name},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.registry_tmp.cleanup()
        self.metrics_tmp.cleanup()
        self.state_tmp.cleanup()

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_payload = self._prompt_payload("sdk-stop")
        run_main(cursor_before_submit.main, stop_payload)
        stop_code, stop_out, stop_err = run_main(
            cursor_post_tool_use.main,
            self._post_payload("sdk-stop"),
        )

        warn_payload = self._prompt_payload("sdk-warn")
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_SPLIT_SCOPE": "warn"}, clear=False):
            run_main(cursor_before_submit.main, warn_payload)
            warn_code, warn_out, warn_err = run_main(
                cursor_post_tool_use.main,
                self._post_payload("sdk-warn"),
            )

        self.assertEqual(0, stop_code)
        self.assertEqual("", stop_err)
        stopped = json.loads(stop_out)
        self.assertFalse(stopped["continue"])
        self.assertEqual("deny", stopped["permission"])
        self.assertIn("split-scope", stopped["user_message"])
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertNotIn("permission", warning)
        self.assertIn("split-scope", warning["additional_context"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        run_main(cursor_before_submit.main, self._prompt_payload("sdk-events"))
        code, out, err = run_main(
            cursor_post_tool_use.main,
            self._post_payload("sdk-events"),
        )

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.metrics_tmp.name) / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("split-scope", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("split-scope.multi-slice-prompt", finding_rows[0]["rule_id"])
        self.assertEqual("split-scope", finding_rows[0]["hook"])
        self.assertEqual("stop", finding_rows[0]["mode"])
        self.assertEqual("registry", finding_rows[0]["mode_source"])

    def _prompt_payload(self, session_id: str) -> dict[str, object]:
        return {
            "prompt": PROMPT,
            "session_id": session_id,
            "registry_path": str(self.registry_path),
        }

    def _post_payload(self, session_id: str) -> dict[str, object]:
        return {
            "session_id": session_id,
            "tool_name": "Edit",
            "registry_path": str(self.registry_path),
        }

    def _registry(self, mode: str) -> Path:
        path = Path(self.registry_tmp.name) / "hooks.toml"
        path.write_text(
            f"""
[hooks.split-scope]
mode = "{mode}"
why_mode = "habit"
summary = "Reminds the agent to split multi-PR work."

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
""".lstrip(),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
