#!/usr/bin/env python3
"""SDK mode and event-row tests for incidence-needs-repetition."""
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
LLM_JUDGE_DIR = HOOK_DIR.parent / "llm-judge"
HOOK = HOOK_DIR / "claude_stop_check.py"
PY = sys.executable
HIT_TEXT = "The test passes on every attempt now; it never fails anymore."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": HIT_TEXT})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
SLOW_HIT = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
RULE_ID = "incidence-needs-repetition.always-claim"
OVERRIDE_ENV = "CATSTACK_HOOK_MODE_INCIDENCE_NEEDS_REPETITION"

sys.path.insert(0, str(LLM_JUDGE_DIR))
from judge_test_base import JudgeTestCase  # noqa: E402


def transcript_with(text: str) -> str:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    handle.write(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }) + "\n")
    handle.close()
    return handle.name


def payload(transcript_path: str, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "transcript_path": transcript_path,
        "last_assistant_message": HIT_TEXT,
    }


class IncidenceNeedsRepetitionSdkModeTest(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.use_runners(ANSWERS_HIT)

    def tearDown(self):
        deadline = time.monotonic() + 10
        while self._jobs() and time.monotonic() < deadline:
            time.sleep(0.05)
        super().tearDown()

    def run_hook(self, payload_data: dict[str, object], env: dict[str, str] | None = None):
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload_data),
            capture_output=True,
            text=True,
            timeout=10,
            env=merged_env,
        )

    def test_mode_override_warn_turns_stop_into_warning(self) -> None:
        path = transcript_with(HIT_TEXT)
        try:
            with tempfile.TemporaryDirectory() as stop_metrics, tempfile.TemporaryDirectory() as warn_metrics:
                stopped = self.run_hook(
                    payload(path, "incidence-sdk-stop"),
                    {"CATSTACK_HOOK_METRICS_DIR": stop_metrics},
                )
                warned = self.run_hook(
                    payload(path, "incidence-sdk-warn"),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": warn_metrics,
                        OVERRIDE_ENV: "warn",
                    },
                )
        finally:
            os.unlink(path)

        self.assertEqual(2, stopped.returncode, stopped.stderr + stopped.stdout)
        self.assertIn("claims behaviour across runs", stopped.stderr)
        self.assertEqual("", stopped.stdout)

        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertEqual("", warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertIn(
            "claims behaviour across runs",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = transcript_with(HIT_TEXT)
        try:
            with tempfile.TemporaryDirectory() as metrics_dir:
                result = self.run_hook(
                    payload(path, "incidence-sdk-events"),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                        OVERRIDE_ENV: "warn",
                    },
                )
                rows = self._rows(Path(metrics_dir))
        finally:
            os.unlink(path)

        finding_rows = [row for row in rows if row["rule_id"] == RULE_ID]
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(finding_rows), rows)
        self.assertEqual("incidence-needs-repetition", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])

    def test_late_verdict_records_unchecked_and_allows(self) -> None:
        self.use_runners(SLOW_HIT)
        path = transcript_with(HIT_TEXT)
        try:
            with tempfile.TemporaryDirectory() as metrics_dir:
                result = self.run_hook(
                    payload(path, "incidence-sdk-unchecked"),
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                        "CATSTACK_INCIDENCE_NEEDS_REPETITION_WAIT_SECONDS": "0.1",
                    },
                )
                rows = self._rows(Path(metrics_dir))
        finally:
            os.unlink(path)

        unchecked_rows = [row for row in rows if row["rule_id"] == RULE_ID and row["action"] == "unchecked"]
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertEqual(1, len(unchecked_rows), rows)
        self.assertEqual("stop", unchecked_rows[0]["mode"])
        self.assertEqual("registry", unchecked_rows[0]["mode_source"])

    def _rows(self, metrics: Path) -> list[dict[str, object]]:
        files = list(metrics.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    def _jobs(self) -> list[str]:
        folder = Path(self.state.name) / "jobs"
        return os.listdir(folder) if folder.is_dir() else []


if __name__ == "__main__":
    unittest.main()
