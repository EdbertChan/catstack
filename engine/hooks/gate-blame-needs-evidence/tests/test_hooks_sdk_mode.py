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
    def payload(self, directory: str) -> dict[str, object]:
        transcript = Path(directory) / "session.jsonl"
        transcript.write_text("\n", encoding="utf-8")
        return {
            "hook_event_name": "Stop",
            "session_id": "gate-blame-sdk-mode",
            "transcript_path": str(transcript),
            "last_assistant_message": "The scope-lock gate is broken and should be disabled.",
        }

    def test_warn_override_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_entrypoint(
                self.payload(tmp),
                {"CATSTACK_HOOK_MODE_GATE_BLAME_NEEDS_EVIDENCE": "warn"},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn("gate-blame-needs-evidence", rendered["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            result = run_entrypoint(
                self.payload(tmp),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_GATE_BLAME_NEEDS_EVIDENCE": "warn",
                },
            )
            rows = [
                json.loads(line)
                for path in metrics.glob("events-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("gate-blame-needs-evidence", rows[0]["hook"])
        self.assertEqual("gate-blame-needs-evidence.unread-gate", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
