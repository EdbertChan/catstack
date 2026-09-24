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
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse.py")

CAUSE = "The worker crashes because the cache is never invalidated."


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


def bash_payload(command: str, cwd: str) -> dict[str, object]:
    return {
        "tool_name": "Bash",
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": command},
        "cwd": cwd,
    }


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = run_entrypoint(
                bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d),
                {"CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn"},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "external-claim-gate",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_entrypoint(
                {
                    **bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d),
                    "session_id": "external-claim-gate-sdk-mode",
                },
                {
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                    "CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn",
                },
            )
            rows = [
                json.loads(line)
                for file in Path(metrics).glob("events-*.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("external-claim-gate", rows[0]["hook"])
        self.assertEqual("external-claim-gate.unverified-claim", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
