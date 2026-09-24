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
PRETOOLUSE = os.path.join(HOOK_DIR, "claude_pretooluse.py")


def bash_payload(command: str, session_id: str = "gh-write-verification-sdk-mode") -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "cwd": HOOK_DIR,
        "tool_input": {"command": command},
    }


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, PRETOOLUSE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as metrics:
            result = run_entrypoint(
                bash_payload("git push origin HEAD >/dev/null 2>&1"),
                {
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                    "CATSTACK_HOOK_MODE_GH_WRITE_VERIFICATION": "warn",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "discards both stdout and stderr",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        command = "gh pr edit 295 --base main; pgrep -f postgres"
        with tempfile.TemporaryDirectory() as metrics:
            result = run_entrypoint(
                bash_payload(command, session_id="gh-write-verification-events"),
                {"CATSTACK_HOOK_METRICS_DIR": metrics},
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(2, len(rows), rows)
        self.assertEqual({row["hook"] for row in rows}, {"gh-write-verification"})
        self.assertEqual(
            {row["rule_id"] for row in rows},
            {
                "gh-write-verification.broken-pr-edit",
                "gh-write-verification.self-matching-process-wait",
            },
        )
        self.assertEqual({row["action"] for row in rows}, {"stopped"})


if __name__ == "__main__":
    unittest.main()
