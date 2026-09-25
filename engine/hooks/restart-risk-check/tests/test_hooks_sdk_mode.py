#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
SDK_DIR = HOOK_DIR.parent / "_sdk"
sys.path.insert(0, str(HOOK_DIR))
sys.path.insert(0, str(SDK_DIR))

import claude_stop_restart_check  # noqa: E402


def _write_transcript(lines: list[dict]) -> str:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for line in lines:
        handle.write(json.dumps(line) + "\n")
    handle.close()
    return handle.name


def _user_line(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _bash_call_line(command: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}],
        },
    }


def _stop_payload(transcript_path: str) -> dict:
    return {
        "hook_event_name": "Stop",
        "session_id": "restart-risk-check-test-session",
        "last_assistant_message": "Restart risk is low on this SSH droplet.",
        "transcript_path": transcript_path,
    }


def _run_claude(payload: dict, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with patch.dict(os.environ, env or {}, clear=False):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    claude_stop_restart_check.main()
                except SystemExit as exc:
                    code = int(exc.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


def _event_rows(metrics_dir: str) -> list[dict]:
    rows: list[dict] = []
    for path in Path(metrics_dir).glob("events-*.jsonl"):
        with path.open(encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


class TestRestartRiskSdkMode(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self):
        transcript = _write_transcript([
            _user_line("check the droplet"),
            _bash_call_line("ls -la"),
        ])
        self.addCleanup(os.unlink, transcript)
        with tempfile.TemporaryDirectory() as metrics_dir:
            code, stdout, stderr = _run_claude(
                _stop_payload(transcript),
                {
                    "CATSTACK_HOOK_MODE_RESTART_RISK_CHECK": "warn",
                    "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                },
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("additionalContext", stdout)
        self.assertIn("remote-host restart is low-risk/safe", stdout)

    def test_writes_one_event_row_per_finding_with_rule_id(self):
        transcript = _write_transcript([
            _user_line("check the droplet"),
            _bash_call_line("ls -la"),
        ])
        self.addCleanup(os.unlink, transcript)
        with tempfile.TemporaryDirectory() as metrics_dir:
            code, _stdout, stderr = _run_claude(
                _stop_payload(transcript),
                {"CATSTACK_HOOK_METRICS_DIR": metrics_dir},
            )
            rows = [
                row for row in _event_rows(metrics_dir)
                if row.get("hook") == "restart-risk-check" and row.get("action") != "followup"
            ]
        self.assertEqual(code, 2)
        self.assertIn("restart", stderr.lower())
        self.assertEqual(1, len(rows))
        self.assertEqual("restart-risk-check.missing-queue-and-session", rows[0]["rule_id"])
        self.assertEqual("stopped", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
