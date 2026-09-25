#!/usr/bin/env python3
"""SDK mode and event-row tests for wrong-check-reflect."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_stop_check.py"
RULE_ID = "wrong-check-reflect.judge-queued"
REFLECT_ENV = "CATSTACK_REFLECT_ENFORCEMENT"
JUDGE_STATE_ENV = "CATSTACK_LLM_JUDGE_STATE_DIR"
JUDGE_RUNNERS_ENV = "CATSTACK_LLM_JUDGE_RUNNERS"
HIT_TEXT = "Correction: the file I pointed you to earlier is not the one in use; the real one is src/b.py."


def stop_payload(registry_path: Path, transcript: Path, session_id: str = "wrong-check-reflect-sdk-test") -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "registry_path": str(registry_path),
        "transcript_path": str(transcript),
        "last_assistant_message": HIT_TEXT,
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


class WrongCheckReflectSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_registry_stop_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="stop")
            transcript = self._transcript(root, "mode.jsonl")
            payload = stop_payload(registry_path, transcript)

            stop_env = self._env(root, "stop-metrics")
            stop_env.pop("CATSTACK_HOOK_MODE_WRONG_CHECK_REFLECT", None)
            stop_result = run_hook(payload, stop_env)
            self._wait_for_jobs(stop_env[JUDGE_STATE_ENV])

            warn_transcript = self._transcript(root, "warn-mode.jsonl")
            warn_payload = stop_payload(registry_path, warn_transcript)
            warn_env = self._env(root, "warn-metrics")
            warn_env["CATSTACK_HOOK_MODE_WRONG_CHECK_REFLECT"] = "warn"
            warn_result = run_hook(warn_payload, warn_env)
            self._wait_for_jobs(warn_env[JUDGE_STATE_ENV])

        self.assertEqual(2, stop_result.returncode, stop_result.stdout)
        self.assertEqual("", stop_result.stdout)
        self.assertIn("wrong-check-reflect", stop_result.stderr)

        self.assertEqual(0, warn_result.returncode, warn_result.stderr)
        self.assertEqual("", warn_result.stderr)
        warn_body = json.loads(warn_result.stdout)
        self.assertIn(
            "wrong-check-reflect",
            warn_body["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="warn")
            metrics = root / "metrics"
            env = self._env(root, "metrics")
            env.pop("CATSTACK_HOOK_MODE_WRONG_CHECK_REFLECT", None)

            result = run_hook(
                stop_payload(registry_path, self._transcript(root, "event.jsonl"), "wrong-check-reflect-event-row"),
                env,
            )
            self._wait_for_jobs(env[JUDGE_STATE_ENV])
            rows = [
                row
                for row in self._event_rows(metrics)
                if row.get("action") == "warned"
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("wrong-check-reflect", rows[0]["hook"])
        self.assertEqual(RULE_ID, rows[0]["rule_id"])
        self.assertEqual("warned", rows[0]["action"])

    def _env(self, root: Path, metrics_name: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "CATSTACK_HOOK_METRICS_DIR": str(root / metrics_name),
                REFLECT_ENV: "1",
                JUDGE_STATE_ENV: str(root / f"{metrics_name}-judge"),
                JUDGE_RUNNERS_ENV: json.dumps(
                    [["fake", [sys.executable, "-c", "print('{\"match\": false}')", "{prompt}"]]]
                ),
                "WRONG_CHECK_REFLECT_STATE_DIR": str(root / f"{metrics_name}-reflect"),
            }
        )
        return env

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
                    "[hooks.wrong-check-reflect]",
                    f'mode = "{mode}"',
                    'why_mode = "habit"',
                    'summary = "Suggests reflect after a claim is taken back."',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _transcript(self, root: Path, name: str) -> Path:
        path = root / name
        path.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": HIT_TEXT}],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _wait_for_jobs(self, state: str) -> None:
        jobs = Path(state) / "jobs"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not jobs.is_dir() or not list(jobs.glob("*.json")):
                return
            time.sleep(0.05)

    def _event_rows(self, metrics: Path) -> list[dict[str, object]]:
        files = list(metrics.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
