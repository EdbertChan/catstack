from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = LIB_DIR / "codex_post_tool_use.py"
ON_HIT = "llm-judge delivered a model verdict"


def registry_with_llm_judge_mode(directory: str, mode: str) -> str:
    path = Path(directory) / "hooks.toml"
    path.write_text(
        textwrap.dedent(
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
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return str(path)


def plant_hit(transcript: Path, verdict_dir: Path, job_id: str) -> None:
    verdict_dir.mkdir(parents=True, exist_ok=True)
    (verdict_dir / f"{job_id}.json").write_text(
        json.dumps(
            {
                "id": job_id,
                "hook": "demo-hook",
                "transcript": str(transcript),
                "outcome": "hit",
                "on_hit": ON_HIT,
                "reason": "all true: match",
                "finished_at": 1,
            }
        ),
        encoding="utf-8",
    )


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for path in sorted(metrics_dir.glob("events-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestHooksSdkMode(unittest.TestCase):
    def test_mode_override_warn_changes_registry_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "session.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            state = root / "state"
            metrics = root / "metrics"
            registry_path = registry_with_llm_judge_mode(tmp, "stop")

            payload = {"hook_event_name": "PostToolUse", "transcript_path": str(transcript), "registry_path": registry_path}
            import hashlib

            digest = hashlib.sha1(str(transcript).encode("utf-8")).hexdigest()[:16]
            plant_hit(transcript, state / "verdicts" / digest, "stops")
            stopped = run_entrypoint(payload, {"CATSTACK_LLM_JUDGE_STATE_DIR": str(state), "CATSTACK_HOOK_METRICS_DIR": str(metrics)})

            plant_hit(transcript, state / "verdicts" / digest, "warns")
            warned = run_entrypoint(
                payload,
                {
                    "CATSTACK_LLM_JUDGE_STATE_DIR": str(state),
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_LLM_JUDGE": "warn",
                },
            )

        self.assertEqual(0, stopped.returncode, stopped.stderr)
        self.assertEqual("block", json.loads(stopped.stdout)["decision"])

        self.assertEqual(0, warned.returncode, warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertNotIn("decision", rendered)
        self.assertEqual(ON_HIT, rendered["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "session.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            state = root / "state"
            metrics = root / "metrics"
            import hashlib

            digest = hashlib.sha1(str(transcript).encode("utf-8")).hexdigest()[:16]
            plant_hit(transcript, state / "verdicts" / digest, "first")
            plant_hit(transcript, state / "verdicts" / digest, "second")

            result = run_entrypoint(
                {"hook_event_name": "PostToolUse", "transcript_path": str(transcript), "session_id": "llm-judge-events"},
                {"CATSTACK_LLM_JUDGE_STATE_DIR": str(state), "CATSTACK_HOOK_METRICS_DIR": str(metrics)},
            )
            rows = [row for row in event_rows(metrics) if row["hook"] == "llm-judge"]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(rows), rows)
        self.assertEqual({"llm-judge.hit"}, {row["rule_id"] for row in rows})
        self.assertEqual(["warned", "warned"], [row["action"] for row in rows])


if __name__ == "__main__":
    unittest.main()
