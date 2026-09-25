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

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import claude_pretooluse  # noqa: E402

POLL_COMMAND = "until grep -q '^exit=' out; do sleep 3; done"


def payload(registry_path: Path, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": POLL_COMMAND, "run_in_background": False},
        "registry_path": str(registry_path),
    }


def run_main(event: dict[str, object]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_pretooluse.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


class HooksSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics_tmp = tempfile.TemporaryDirectory()
        self.registry_tmp = tempfile.TemporaryDirectory()
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

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_code, stop_out, stop_err = run_main(
            payload(self.registry_path, "wait-needs-wakeup-stop")
        )

        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_WAIT_NEEDS_WAKEUP": "warn"}, clear=False):
            warn_code, warn_out, warn_err = run_main(
                payload(self.registry_path, "wait-needs-wakeup-warn")
            )

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("wait-needs-wakeup", stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        output = warning["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertIn("wait-needs-wakeup", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        code, out, err = run_main(
            payload(self.registry_path, "wait-needs-wakeup-events")
        )

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.metrics_tmp.name) / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("wait-needs-wakeup", err)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("wait-needs-wakeup.foreground-poll-loop", finding_rows[0]["rule_id"])
        self.assertEqual("wait-needs-wakeup", finding_rows[0]["hook"])
        self.assertEqual("stop", finding_rows[0]["mode"])
        self.assertEqual("registry", finding_rows[0]["mode_source"])

    def _registry(self, mode: str) -> Path:
        path = Path(self.registry_tmp.name) / "hooks.toml"
        path.write_text(
            f"""
[hooks.wait-needs-wakeup]
mode = "{mode}"
why_mode = "attention"
summary = "Stops waiting language with no time or wake-up set."

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
