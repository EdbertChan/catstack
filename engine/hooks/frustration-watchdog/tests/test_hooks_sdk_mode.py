from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_stop_check.py"
WAITING = "i am waiting for you to do something"
NARRATION = "I'm cancelling the stale captures and preparing the environment for the next phase."


def transcript_with(text: str) -> str:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    handle.write(json.dumps({
        "type": "user",
        "timestamp": "2026-08-18T02:13:30Z",
        "message": {"role": "user", "content": text},
    }) + "\n")
    handle.close()
    return handle.name


def payload(transcript_path: str) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": "frustration-watchdog-sdk-mode",
        "transcript_path": transcript_path,
        "last_assistant_message": NARRATION,
    }


def run_hook(payload_data: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_turns_stop_into_warning(self) -> None:
        path = transcript_with(WAITING)
        try:
            with tempfile.TemporaryDirectory() as metrics_dir:
                result = run_hook(
                    payload(path),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                        "CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn",
                    },
                )
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "impatience-shaped",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = transcript_with(WAITING)
        try:
            with tempfile.TemporaryDirectory() as metrics_dir:
                result = run_hook(
                    payload(path),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                        "CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn",
                    },
                )
                rows = [
                    json.loads(line)
                    for file in Path(metrics_dir).glob("events-*.jsonl")
                    for line in file.read_text(encoding="utf-8").splitlines()
                ]
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("frustration-watchdog", rows[0]["hook"])
        self.assertEqual("frustration-watchdog.no-visible-next-step", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
