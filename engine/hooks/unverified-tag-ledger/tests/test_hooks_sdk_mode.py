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

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, HOOK)

import claude_stop_check  # noqa: E402

TAG = (
    "{{CAT-UNVERIFIED: that it widened scope past the one session I gave it "
    "-- cannot verify: it never answered when asked twice}}"
)


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
        self.ledger_tmp = tempfile.TemporaryDirectory()
        self.metrics_tmp = tempfile.TemporaryDirectory()
        self.registry_tmp = tempfile.TemporaryDirectory()
        self.registry_path = self._registry("stop")
        self.env = patch.dict(
            os.environ,
            {
                "CATSTACK_TAG_LEDGER_DIR": self.ledger_tmp.name,
                "CATSTACK_HOOK_METRICS_DIR": self.metrics_tmp.name,
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.registry_tmp.cleanup()
        self.metrics_tmp.cleanup()
        self.ledger_tmp.cleanup()

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_code, stop_out, stop_err = run_main(
            self._payload("ledger-stop")
        )

        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_UNVERIFIED_TAG_LEDGER": "warn"}, clear=False):
            warn_code, warn_out, warn_err = run_main(
                self._payload("ledger-warn")
            )

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("ran no verification tool", stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        output = warning["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("ran no verification tool", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        code, out, err = run_main(self._payload("ledger-events"))

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.metrics_tmp.name) / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("ran no verification tool", err)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("unverified-tag-ledger.no-verification-tool", finding_rows[0]["rule_id"])
        self.assertEqual("unverified-tag-ledger", finding_rows[0]["hook"])
        self.assertEqual("stop", finding_rows[0]["mode"])
        self.assertEqual("registry", finding_rows[0]["mode_source"])

    def _payload(self, session_id: str) -> dict[str, object]:
        return {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "last_assistant_message": TAG,
            "transcript_path": self._transcript_without_tools(),
            "registry_path": str(self.registry_path),
        }

    def _transcript_without_tools(self) -> str:
        source = os.path.join(FIXTURES, "claude-transcript.jsonl")
        path = os.path.join(self.ledger_tmp.name, "transcript.jsonl")
        with open(source, encoding="utf-8") as handle:
            lines = [line for line in handle if '"tool_use"' not in line]
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        return path

    def _registry(self, mode: str) -> Path:
        path = Path(self.registry_tmp.name) / "hooks.toml"
        path.write_text(
            f"""
[hooks.unverified-tag-ledger]
mode = "{mode}"
why_mode = "attention"
summary = "Stops when unchecked claims pile up."

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
