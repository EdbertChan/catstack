#!/usr/bin/env python3
"""SDK mode and event-row tests for wait-needs-wakeup."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse.py"
RULE_ID = "wait-needs-wakeup.foreground-poll"


def bash_payload(registry_path: Path, session_id: str = "wait-needs-wakeup-sdk-test") -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "registry_path": str(registry_path),
        "tool_name": "Bash",
        "tool_input": {
            "command": "until gh pr view 1 --json state -q .state | grep -q MERGED; do sleep 30; done",
        },
    }


def run_hook(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class WaitNeedsWakeupSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_registry_stop_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="stop")
            payload = bash_payload(registry_path)

            stop_env = os.environ.copy()
            stop_env["CATSTACK_HOOK_METRICS_DIR"] = str(root / "stop-metrics")
            stop_env.pop("CATSTACK_HOOK_MODE_WAIT_NEEDS_WAKEUP", None)
            stop_result = run_hook(payload, stop_env)

            warn_env = os.environ.copy()
            warn_env.update(
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(root / "warn-metrics"),
                    "CATSTACK_HOOK_MODE_WAIT_NEEDS_WAKEUP": "warn",
                }
            )
            warn_result = run_hook(payload, warn_env)

        self.assertEqual(2, stop_result.returncode, stop_result.stdout)
        self.assertEqual("", stop_result.stdout)
        self.assertIn("wait-needs-wakeup", stop_result.stderr)

        self.assertEqual(0, warn_result.returncode, warn_result.stderr)
        self.assertEqual("", warn_result.stderr)
        warn_body = json.loads(warn_result.stdout)
        self.assertIn("wait-needs-wakeup", warn_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="stop")
            metrics = root / "metrics"
            env = os.environ.copy()
            env["CATSTACK_HOOK_METRICS_DIR"] = str(metrics)
            env.pop("CATSTACK_HOOK_MODE_WAIT_NEEDS_WAKEUP", None)

            result = run_hook(bash_payload(registry_path, "wait-needs-wakeup-event-row"), env)
            rows = self._event_rows(metrics)

        self.assertEqual(2, result.returncode, result.stdout)
        self.assertEqual(1, len(rows))
        self.assertEqual("wait-needs-wakeup", rows[0]["hook"])
        self.assertEqual(RULE_ID, rows[0]["rule_id"])
        self.assertEqual("stopped", rows[0]["action"])

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
                    "[hooks.wait-needs-wakeup]",
                    f'mode = "{mode}"',
                    'why_mode = "attention"',
                    'summary = "Stops waiting language with no time or wake-up set."',
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
