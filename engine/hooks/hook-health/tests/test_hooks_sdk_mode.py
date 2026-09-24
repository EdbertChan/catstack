from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]


def registry_with_hook_health_mode(directory: Path, mode: str) -> Path:
    path = directory / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [hooks.hook-health]
            mode = "{mode}"
            why_mode = "habit"
            summary = "Notes hooks that crashed."

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
    return path


def failed_run(harness: str = "codex", hook: str = "demo") -> dict[str, object]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "harness": harness,
        "hook": hook,
        "script": "x.py",
        "event": "UserPromptSubmit",
        "session_id": "source-session",
        "outcome": "crashed",
        "exit_code": 1,
        "duration_ms": 4,
        "stdout_bytes": 0,
        "stderr_tail": "boom\nmore",
    }


def write_runs(metrics_dir: Path, rows: list[dict[str, object]]) -> None:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    with (metrics_dir / "runs.jsonl").open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def run_entrypoint(
    script: str,
    metrics_dir: Path,
    registry_path: Path | None = None,
    env: dict[str, str] | None = None,
    session_id: str = "hook-health-sdk-mode",
) -> subprocess.CompletedProcess[str]:
    payload: dict[str, object] = {"session_id": session_id}
    if registry_path is not None:
        payload["registry_path"] = str(registry_path)
    hook_env = os.environ.copy()
    hook_env.update({"CATSTACK_HOOK_METRICS_DIR": str(metrics_dir)})
    hook_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=hook_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


class HookHealthSdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_registry_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = registry_with_hook_health_mode(root, "stop")

            stop_metrics = root / "stop-metrics"
            write_runs(stop_metrics, [failed_run()])
            stopped = run_entrypoint(
                "codex_prompt_submit.py",
                stop_metrics,
                registry_path,
                session_id="hook-health-stop",
            )

            warn_metrics = root / "warn-metrics"
            write_runs(warn_metrics, [failed_run()])
            warned = run_entrypoint(
                "codex_prompt_submit.py",
                warn_metrics,
                registry_path,
                env={"CATSTACK_HOOK_MODE_HOOK_HEALTH": "warn"},
                session_id="hook-health-warn",
            )

        self.assertEqual(0, stopped.returncode, stopped.stderr)
        self.assertEqual("block", json.loads(stopped.stdout)["decision"])

        self.assertEqual(0, warned.returncode, warned.stderr)
        body = json.loads(warned.stdout)
        self.assertNotIn("decision", body)
        self.assertIn("additionalContext", body["hookSpecificOutput"])
        self.assertIn("hook-health: 1 hook run(s) failed", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_dir = Path(tmp) / "metrics"
            write_runs(metrics_dir, [failed_run(harness="claude")])
            result = run_entrypoint(
                "claude_prompt_submit.py",
                metrics_dir,
                env={"CATSTACK_HOOK_MODE_HOOK_HEALTH": "warn"},
                session_id="hook-health-events",
            )
            rows = event_rows(metrics_dir)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("hook-health", rows[0]["hook"])
        self.assertEqual("hook-health.failed-run", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
