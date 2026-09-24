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
ENTRYPOINT = HOOK_DIR / "claude_pretooluse.py"


def registry_with_pr_schema_gate_mode(directory: str, mode: str) -> str:
    path = Path(directory) / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [hooks.pr-schema-gate]
            mode = "{mode}"
            why_mode = "habit"
            summary = "Notes PR text that breaks the repo format."

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


def repo_with_validator(root: Path) -> Path:
    repo = root / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "validate-pr-body.mjs").write_text("// stub\n", encoding="utf-8")
    return repo


def bash_payload(command: str, cwd: Path, **extra: object) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "pr-schema-gate-sdk-mode",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
        **extra,
    }


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
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
            repo = repo_with_validator(root)
            metrics = root / "metrics"
            registry_path = registry_with_pr_schema_gate_mode(tmp, "stop")
            payload = bash_payload(
                "gh pr edit 7 --body inline",
                repo,
                registry_path=registry_path,
            )

            stopped = run_entrypoint(payload, {"CATSTACK_HOOK_METRICS_DIR": str(metrics)})
            warned = run_entrypoint(
                payload,
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_PR_SCHEMA_GATE": "warn",
                },
            )

        self.assertEqual(2, stopped.returncode, stopped.stderr)
        self.assertIn("could not check this PR text", stopped.stderr)

        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertIn("could not check this PR text", warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertIn(
            "could not check this PR text",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = repo_with_validator(root)
            metrics = root / "metrics"
            result = run_entrypoint(
                bash_payload(
                    "gh pr edit 1 --body inline-one; gh pr edit 2 --body inline-two",
                    repo,
                    session_id="pr-schema-gate-events",
                ),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_PR_SCHEMA_GATE": "warn",
                },
            )
            rows = [row for row in event_rows(metrics) if row["hook"] == "pr-schema-gate"]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(rows), rows)
        self.assertEqual({"pr-schema-gate.unchecked-pr-text"}, {row["rule_id"] for row in rows})
        self.assertEqual(["warned", "warned"], [row["action"] for row in rows])


if __name__ == "__main__":
    unittest.main()
