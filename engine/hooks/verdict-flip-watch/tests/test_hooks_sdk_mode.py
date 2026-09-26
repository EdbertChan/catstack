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

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN_REPLY = "Opened the PR; here is the link."


def payload(registry_path: Path, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "last_assistant_message": CLEAN_REPLY,
        "transcript_path": str(FIXTURES / "flip.jsonl"),
        "registry_path": str(registry_path),
    }


def run_main(event: dict[str, object]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


class HooksSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics_tmp = tempfile.TemporaryDirectory()
        self.registry_tmp = tempfile.TemporaryDirectory()
        self.state_tmp = tempfile.TemporaryDirectory()
        self.registry_path = self._registry("stop")
        self._prev_state_dir = detect.STATE_DIR
        detect.STATE_DIR = self.state_tmp.name
        self.env = patch.dict(
            os.environ,
            {
                "CATSTACK_HOOK_METRICS_DIR": self.metrics_tmp.name,
                "CATSTACK_REFLECT_ENFORCEMENT": "1",
                "VERDICT_FLIP_WATCH_STATE_DIR": self.state_tmp.name,
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        detect.STATE_DIR = self._prev_state_dir
        self.state_tmp.cleanup()
        self.registry_tmp.cleanup()
        self.metrics_tmp.cleanup()

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_code, stop_out, stop_err = run_main(
            payload(self.registry_path, "verdict-flip-stop")
        )

        self._fresh_state_dir()
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_VERDICT_FLIP_WATCH": "warn"}, clear=False):
            warn_code, warn_out, warn_err = run_main(
                payload(self.registry_path, "verdict-flip-warn")
            )

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("verdict-flip-watch", stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        output = warning["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("verdict-flip-watch", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        code, out, err = run_main(
            payload(self.registry_path, "verdict-flip-events")
        )

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.metrics_tmp.name) / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("verdict-flip-watch", err)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("verdict-flip-watch.verdict-flipped", finding_rows[0]["rule_id"])
        self.assertEqual("verdict-flip-watch", finding_rows[0]["hook"])
        self.assertEqual("stop", finding_rows[0]["mode"])
        self.assertEqual("registry", finding_rows[0]["mode_source"])

    def _fresh_state_dir(self) -> None:
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        detect.STATE_DIR = fresh.name
        os.environ["VERDICT_FLIP_WATCH_STATE_DIR"] = fresh.name

    def _registry(self, mode: str) -> Path:
        path = Path(self.registry_tmp.name) / "hooks.toml"
        path.write_text(
            f"""
[hooks.verdict-flip-watch]
mode = "{mode}"
why_mode = "habit"
summary = "Notes a check that passed earlier and failed later."

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
