from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_hooks import NARRATION, WAITING, human, transcript_lines, tool_turn

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_stop_check.py"


def payload(transcript_path: str) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": "frustration-watchdog-sdk-mode",
        "transcript_path": transcript_path,
        "last_assistant_message": NARRATION,
        "stop_hook_active": False,
    }


def run_hook(data: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.pop("CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG", None)
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_turns_stop_into_warning(self) -> None:
        transcript = transcript_lines([human(WAITING)])
        try:
            result = run_hook(
                payload(transcript),
                {"CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn"},
            )
        finally:
            os.unlink(transcript)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        output = json.loads(result.stdout)
        self.assertIn(
            "The user's last message was impatience-shaped (waiting)",
            output["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as metrics_dir:
            transcript = transcript_lines([human(WAITING)] + tool_turn("Created PR #12", is_error=False))
            try:
                result = run_hook(
                    payload(transcript),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                        "CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn",
                    },
                )
            finally:
                os.unlink(transcript)
            rows = self._event_rows(metrics_dir)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("frustration-watchdog", rows[0]["hook"])
        self.assertEqual("frustration-watchdog.waiting", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])

    def _event_rows(self, metrics_dir: str) -> list[dict[str, object]]:
        files = list(Path(metrics_dir).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
