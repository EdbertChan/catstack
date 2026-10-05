from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "ci" / "check_hook_fleet_canary.py"


class HookFleetCanaryCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.metrics = Path(self.tmp.name)
        self.log = self.metrics / "runs.jsonl"

    def row(self, outcome: str, *, dispatch: bool = False, uid: str = "u") -> dict[str, object]:
        row: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "harness": "claude",
            "hook": "fixture",
            "script": "hook.py",
            "event": "SubagentStop",
            "event_uid": uid,
            "session_id": uid,
            "outcome": outcome,
            "exit_code": 0,
            "duration_ms": 10,
            "stdout_bytes": 0,
            "stderr_tail": "",
        }
        if dispatch:
            row["dispatch_path"] = "sdk"
        return row

    def write_rows(self, rows: list[dict[str, object]]) -> None:
        with self.log.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def run_check(self) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "CATSTACK_HOOK_METRICS_DIR": str(self.metrics)}
        return subprocess.run(
            [sys.executable, str(CHECK), "--baseline-window", "pre-dispatcher"],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_passes_when_spoke_is_stable_and_failures_improve(self) -> None:
        self.write_rows(
            [self.row("spoke", uid=f"pre-{index}") for index in range(8)]
            + [self.row("timed_out", uid="pre-timeout"), self.row("crashed", uid="pre-crash")]
            + [self.row("spoke", dispatch=True, uid=f"post-{index}") for index in range(8)]
            + [self.row("silent", dispatch=True, uid="post-silent-1"), self.row("silent", dispatch=True, uid="post-silent-2")]
        )

        result = self.run_check()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS SubagentStop", result.stdout)

    def test_fails_when_subagent_stop_spoke_rate_collapses(self) -> None:
        self.write_rows(
            [self.row("spoke", uid=f"pre-{index}") for index in range(8)]
            + [self.row("silent", uid=f"pre-silent-{index}") for index in range(2)]
            + [self.row("spoke", dispatch=True, uid=f"post-{index}") for index in range(6)]
            + [self.row("silent", dispatch=True, uid=f"post-silent-{index}") for index in range(4)]
        )

        result = self.run_check()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("spoke-rate fell materially", result.stdout)

    def test_warns_when_post_dispatcher_rows_are_missing(self) -> None:
        self.write_rows([self.row("spoke", uid="pre")])

        result = self.run_check()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unchecked: no post-dispatcher canary rows for SubagentStop", result.stdout)


if __name__ == "__main__":
    unittest.main()
