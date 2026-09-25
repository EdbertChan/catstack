from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_hooks import REAL_FIRE


HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


class SdkModeTest(unittest.TestCase):
    def payload(self) -> dict[str, object]:
        return {
            "hook_event_name": "Stop",
            "session_id": "prove-it-ship-gate-sdk-mode",
            "last_assistant_message": REAL_FIRE[0],
        }

    def test_warn_override_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            result = run_entrypoint(
                self.payload(),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_PROVE_IT_SHIP_GATE": "warn",
                },
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn("prove-it-ship-gate", rendered["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            result = run_entrypoint(
                self.payload(),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_PROVE_IT_SHIP_GATE": "warn",
                },
            )
            rows = [
                json.loads(line)
                for path in metrics.glob("events-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("prove-it-ship-gate", rows[0]["hook"])
        self.assertEqual("prove-it-ship-gate.unproven-live-claim", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
