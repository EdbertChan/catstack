from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_stop_check.py")
WAITING = "i am waiting for you to do something"
NARRATION = "I'm cancelling the stale captures and preparing the environment for the next phase."


def transcript_with_waiting_user(directory: str) -> str:
    path = os.path.join(directory, "transcript.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "user",
            "timestamp": "2026-08-18T02:13:30Z",
            "message": {"role": "user", "content": WAITING},
        }) + "\n")
        handle.write(json.dumps({
            "type": "assistant",
            "message": {"id": "m1", "usage": {}, "content": []},
        }) + "\n")
    return path


def firing_payload(transcript_path: str, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "transcript_path": transcript_path,
        "last_assistant_message": NARRATION,
    }


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, ENTRYPOINT],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def event_rows(directory: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for file in Path(directory).glob("events-*.jsonl")
        for line in file.read_text(encoding="utf-8").splitlines()
    ]


class FrustrationWatchdogSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = transcript_with_waiting_user(tmp)
            stopped = run_entrypoint(
                firing_payload(transcript, "frustration-watchdog-stop"),
                {"CATSTACK_HOOK_METRICS_DIR": tmp},
            )
            warned = run_entrypoint(
                firing_payload(transcript, "frustration-watchdog-warn"),
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn",
                },
            )

        self.assertEqual(2, stopped.returncode)
        self.assertIn("impatience-shaped (waiting)", stopped.stderr)
        self.assertEqual("", stopped.stdout)

        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertEqual("", warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertEqual("Stop", rendered["hookSpecificOutput"]["hookEventName"])
        self.assertIn(
            "impatience-shaped (waiting)",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = transcript_with_waiting_user(tmp)
            result = run_entrypoint(
                firing_payload(transcript, "frustration-watchdog-event-row"),
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_FRUSTRATION_WATCHDOG": "warn",
                },
            )
            rows = event_rows(tmp)

        finding_rows = [row for row in rows if row["action"] == "warned"]
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("frustration-watchdog", finding_rows[0]["hook"])
        self.assertEqual("frustration-watchdog.no-visible-handoff", finding_rows[0]["rule_id"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
