from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse.py"

CAUSE = "The worker crashes because the cache is never invalidated."
RESOLUTION = "Verified, the upload succeeds after the retry change."


def bash_payload(command: str, cwd: str, session_id: str = "external-claim-gate-test") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    }


def run_hook(payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=hook_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d),
                {
                    "CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn",
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("external-claim-gate", result.stderr)

    def test_writes_one_event_row_per_finding_with_rule_id(self) -> None:
        command = (
            f"gh issue comment 1 --body '{CAUSE}'; "
            f"gh issue comment 2 --body '{RESOLUTION}'"
        )
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                bash_payload(command, d, session_id="external-claim-gate-events"),
                {"CATSTACK_HOOK_METRICS_DIR": metrics},
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual({row["hook"] for row in rows}, {"external-claim-gate"})
        self.assertEqual(
            {row["rule_id"] for row in rows},
            {"external-claim-gate.unverified-claim"},
        )


if __name__ == "__main__":
    unittest.main()
