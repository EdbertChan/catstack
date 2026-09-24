from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = HOOK_DIR / "claude_posttooluse.py"

TIMEOUT = 'Error: Task "{name}" did not reach status "completed" within 55000ms'


def bash_payload(command: str, registry_path: Path, session_id: str = "repeat-error-stop-sdk") -> dict[str, object]:
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUseFailure",
        "registry_path": str(registry_path),
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": "Exit code 1\n" + TIMEOUT.format(name="alpha"),
        "is_interrupt": False,
    }


def write_registry(directory: Path, mode: str) -> Path:
    path = directory / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [hooks.repeat-error-stop]
            mode = "{mode}"
            why_mode = "habit"
            summary = "Test registry entry."

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


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=hook_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root, "stop")
            state = root / "state"
            metrics = root / "metrics"
            env = {
                "REPEAT_ERROR_STOP_STATE_DIR": str(state),
                "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                "CATSTACK_HOOK_MODE_REPEAT_ERROR_STOP": "warn",
            }

            for _ in range(2):
                run_entrypoint(bash_payload("pnpm test e2e", registry), env)
            result = run_entrypoint(bash_payload("pnpm test e2e", registry), env)
            rows = event_rows(metrics)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        body = json.loads(result.stdout)
        self.assertNotIn("decision", body)
        self.assertIn("additionalContext", body["hookSpecificOutput"])
        finding_rows = [row for row in rows if row["rule_id"] == "repeat-error-stop.repeated-error"]
        self.assertEqual(1, len(finding_rows), rows)
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root, "warn")
            state = root / "state"
            metrics = root / "metrics"
            env = {
                "REPEAT_ERROR_STOP_STATE_DIR": str(state),
                "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                "CATSTACK_HOOK_MODE_REPEAT_ERROR_STOP": "",
            }

            for _ in range(3):
                result = run_entrypoint(bash_payload("pnpm test e2e", registry, "repeat-error-stop-events"), env)
            rows = event_rows(metrics)

        self.assertEqual(0, result.returncode, result.stderr)
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(1, len(finding_rows), rows)
        self.assertEqual("repeat-error-stop", finding_rows[0]["hook"])
        self.assertEqual("repeat-error-stop.repeated-error", finding_rows[0]["rule_id"])


if __name__ == "__main__":
    unittest.main()
