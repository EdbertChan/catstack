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


def bash_payload(command: str, cwd: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "external-claim-gate-test",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
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


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_turns_stop_into_warning(self) -> None:
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as metrics_dir:
            env = os.environ.copy()
            env.update(
                {
                    "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                    "CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn",
                }
            )
            result = run_hook(
                bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", cwd),
                env,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("external-claim-gate", output["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as metrics_dir:
            env = os.environ.copy()
            env.pop("CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE", None)
            env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
            result = run_hook(
                bash_payload(
                    (
                        f"gh issue comment 1 --body '{CAUSE}'; "
                        f"gh pr comment 2 --body '{RESOLUTION}'"
                    ),
                    cwd,
                ),
                env,
            )
            rows = self._event_rows(metrics_dir)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual(2, len(rows))
        self.assertEqual(
            ["external-claim-gate.unverified-claim", "external-claim-gate.unverified-claim"],
            [row["rule_id"] for row in rows],
        )
        self.assertTrue(all(row["hook"] == "external-claim-gate" for row in rows))

    def _event_rows(self, metrics_dir: str) -> list[dict[str, object]]:
        files = list(Path(metrics_dir).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
