#!/usr/bin/env python3
"""SDK mode and event-row tests for unverified-tag-ledger."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
HOOK = HOOK_DIR / "claude_stop_check.py"
FIXTURES = HERE / "fixtures"
REAL_TRANSCRIPT = FIXTURES / "claude-transcript.jsonl"
RULE_ID = "unverified-tag-ledger.untried-tag"
TAG = (
    "{{CAT-UNVERIFIED: that it widened scope past the one session I gave it "
    "-- cannot verify: it never answered when asked twice}}"
)


def payload(registry_path: Path, transcript_path: Path, session_id: str = "tag-ledger-sdk-test") -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "registry_path": str(registry_path),
        "last_assistant_message": TAG,
        "transcript_path": str(transcript_path),
    }


def run_hook(payload_data: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class UnverifiedTagLedgerSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_registry_stop_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = self._transcript_without_tools(root)
            registry_path = self._registry(root, mode="stop")
            event = payload(registry_path, transcript)

            stop_env = os.environ.copy()
            stop_env.update({"CATSTACK_TAG_LEDGER_DIR": str(root / "stop-ledger")})
            stop_env["CATSTACK_HOOK_METRICS_DIR"] = str(root / "stop-metrics")
            stop_env.pop("CATSTACK_HOOK_MODE_UNVERIFIED_TAG_LEDGER", None)
            stop_result = run_hook(event, stop_env)

            warn_env = os.environ.copy()
            warn_env.update(
                {
                    "CATSTACK_TAG_LEDGER_DIR": str(root / "warn-ledger"),
                    "CATSTACK_HOOK_METRICS_DIR": str(root / "warn-metrics"),
                    "CATSTACK_HOOK_MODE_UNVERIFIED_TAG_LEDGER": "warn",
                }
            )
            warn_result = run_hook(event, warn_env)

        self.assertEqual(2, stop_result.returncode, stop_result.stdout)
        self.assertEqual("", stop_result.stdout)
        self.assertIn("ran no verification tool", stop_result.stderr)

        self.assertEqual(0, warn_result.returncode, warn_result.stderr)
        self.assertEqual("", warn_result.stderr)
        body = json.loads(warn_result.stdout)
        self.assertIn("ran no verification tool", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = self._transcript_without_tools(root)
            registry_path = self._registry(root, mode="stop")
            metrics = root / "metrics"
            env = os.environ.copy()
            env.update(
                {
                    "CATSTACK_TAG_LEDGER_DIR": str(root / "ledger"),
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                }
            )
            env.pop("CATSTACK_HOOK_MODE_UNVERIFIED_TAG_LEDGER", None)

            result = run_hook(payload(registry_path, transcript, "tag-ledger-event-row"), env)
            rows = self._event_rows(metrics)

        self.assertEqual(2, result.returncode, result.stdout)
        self.assertEqual(1, len(rows))
        self.assertEqual("unverified-tag-ledger", rows[0]["hook"])
        self.assertEqual(RULE_ID, rows[0]["rule_id"])
        self.assertEqual("stopped", rows[0]["action"])

    def _transcript_without_tools(self, root: Path) -> Path:
        lines = [
            line
            for line in REAL_TRANSCRIPT.read_text(encoding="utf-8").splitlines()
            if '"tool_use"' not in line
        ]
        path = root / "transcript.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _registry(self, root: Path, mode: str) -> Path:
        path = root / "hooks.toml"
        path.write_text(
            "\n".join(
                [
                    "[thresholds]",
                    "min_closed_findings = 30",
                    "promote_max_ignore_rate = 0.02",
                    "demote_min_ignore_rate = 0.10",
                    "review_min_ignore_rate = 0.50",
                    "review_min_unchecked_rate = 0.05",
                    "followup_window_checks = 3",
                    "",
                    "[hooks.unverified-tag-ledger]",
                    f'mode = "{mode}"',
                    'why_mode = "attention"',
                    'summary = "Stops when unchecked claims pile up."',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _event_rows(self, metrics: Path) -> list[dict[str, object]]:
        files = list(metrics.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
