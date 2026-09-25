#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
CODEX_POST_TOOL_USE = HOOK_DIR / "codex_post_tool_use.py"

PY = sys.executable
ON_HIT = "judge hit text"


def write_registry(path: Path, mode: str) -> None:
    path.write_text(
        f"""
[hooks.llm-judge]
mode = "{mode}"
why_mode = "habit"
summary = "Shared model check that other hooks call."

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
""".lstrip(),
        encoding="utf-8",
    )


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [PY, str(CODEX_POST_TOOL_USE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )


def plant_hit(state: Path, transcript: Path, job_id: str = "hit") -> None:
    digest = __import__("hashlib").sha1(str(transcript).encode("utf-8")).hexdigest()[:16]
    folder = state / "verdicts" / digest
    folder.mkdir(parents=True)
    (folder / f"{job_id}.json").write_text(
        json.dumps(
            {
                "id": job_id,
                "hook": "demo-hook",
                "rule_id": "demo-hook.match",
                "transcript": str(transcript),
                "outcome": "hit",
                "on_hit": ON_HIT,
                "reason": "all true: match",
                "finished_at": 1,
            }
        ),
        encoding="utf-8",
    )


class LlmJudgeSdkModeTest(unittest.TestCase):
    def payload(self, transcript: Path, registry: Path | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "hook_event_name": "PostToolUse",
            "session_id": "llm-judge-sdk-mode",
            "transcript_path": str(transcript),
        }
        if registry is not None:
            payload["registry_path"] = str(registry)
        return payload

    def test_warn_override_changes_stop_registry_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            registry = tmp / "hooks.toml"
            write_registry(registry, "stop")

            stop_state = tmp / "stop-state"
            stop_metrics = tmp / "stop-metrics"
            stop_transcript = tmp / "stop.jsonl"
            stop_transcript.write_text("{}\n", encoding="utf-8")
            plant_hit(stop_state, stop_transcript)
            stop_result = run_entrypoint(
                self.payload(stop_transcript, registry),
                {
                    "CATSTACK_LLM_JUDGE_STATE_DIR": str(stop_state),
                    "CATSTACK_HOOK_METRICS_DIR": str(stop_metrics),
                },
            )

            warn_state = tmp / "warn-state"
            warn_metrics = tmp / "warn-metrics"
            warn_transcript = tmp / "warn.jsonl"
            warn_transcript.write_text("{}\n", encoding="utf-8")
            plant_hit(warn_state, warn_transcript)
            warn_result = run_entrypoint(
                self.payload(warn_transcript, registry),
                {
                    "CATSTACK_LLM_JUDGE_STATE_DIR": str(warn_state),
                    "CATSTACK_HOOK_METRICS_DIR": str(warn_metrics),
                    "CATSTACK_HOOK_MODE_LLM_JUDGE": "warn",
                },
            )

        self.assertEqual(0, stop_result.returncode, stop_result.stderr)
        self.assertEqual(0, warn_result.returncode, warn_result.stderr)
        stop_body = json.loads(stop_result.stdout)
        warn_body = json.loads(warn_result.stdout)
        self.assertEqual("block", stop_body["decision"])
        self.assertIn(ON_HIT, stop_body["reason"])
        self.assertNotIn("decision", warn_body)
        self.assertEqual(ON_HIT, warn_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            state = tmp / "state"
            metrics = tmp / "metrics"
            transcript = tmp / "session.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            plant_hit(state, transcript)

            result = run_entrypoint(
                self.payload(transcript),
                {
                    "CATSTACK_LLM_JUDGE_STATE_DIR": str(state),
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                },
            )
            rows = event_rows(metrics)

        llm_rows = [row for row in rows if row["hook"] == "llm-judge" and row["rule_id"]]
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(ON_HIT, result.stdout)
        self.assertEqual(1, len(llm_rows))
        self.assertEqual("llm-judge.hit-verdict", llm_rows[0]["rule_id"])
        self.assertEqual("warn", llm_rows[0]["mode"])
        self.assertEqual("warned", llm_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
