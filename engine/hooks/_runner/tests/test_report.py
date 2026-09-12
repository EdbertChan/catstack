from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[1]
REPORT = RUNNER_DIR / "report.py"


class ReportCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.metrics = Path(self.tmp.name) / "metrics"
        self.metrics.mkdir(parents=True)
        self.log = self.metrics / "runs.jsonl"

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home), "CATSTACK_HOOK_METRICS_DIR": str(self.metrics)}

    def run_report(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPORT), *args],
            capture_output=True,
            text=True,
            env=self.env(),
            timeout=10,
        )

    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")

    def row(self, harness: str, hook: str, script: str, outcome: str, **extra: object) -> dict[str, object]:
        data: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "harness": harness,
            "hook": hook,
            "script": script,
            "event": "UserPromptSubmit",
            "session_id": "s1",
            "outcome": outcome,
            "exit_code": 0,
            "duration_ms": 10,
            "stdout_bytes": 0,
            "stderr_tail": "",
        }
        data.update(extra)
        return data

    def seed_configs(self) -> None:
        self.write_json(
            self.home / ".claude" / "settings.json",
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 $HOME/.claude/hooks/_runner/run.py --timeout 9 hook-a/a.py",
                                }
                            ]
                        }
                    ]
                }
            },
        )
        self.write_json(
            self.home / ".cursor" / "hooks.json",
            {
                "hooks": {
                    "beforeSubmitPrompt": [
                        {
                            "command": "python3 $HOME/.cursor/hooks/_runner/run.py --timeout 9 hook-b/b.py",
                        }
                    ]
                }
            },
        )
        self.write_json(
            self.home / ".codex" / "hooks.json",
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 $HOME/.codex/hooks/_runner/run.py --timeout 9 hook-c/c.py",
                                }
                            ]
                        }
                    ]
                }
            },
        )

    def write_rows(self, rows: list[dict[str, object]], malformed: bool = False) -> None:
        with self.log.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
            if malformed:
                handle.write("{bad\n")

    def test_seeded_rows_include_no_record_and_unregistered(self) -> None:
        self.seed_configs()
        self.write_rows(
            [
                self.row("claude", "hook-a", "a.py", "crashed", exit_code=1, stderr_tail="boom\nsecond"),
                self.row("codex", "hook-c", "c.py", "silent", duration_ms=20),
                self.row("claude", "loose", "z.py", "timed_out", exit_code=1, stderr_tail="slow"),
            ],
            malformed=True,
        )
        result = self.run_report("--since", "24h")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped 1 malformed row(s)", result.stdout)
        self.assertIn("claude hook-a/a.py 1 0 0 0 1 0 0 10 boom", result.stdout)
        self.assertIn("cursor hook-b/b.py no record", result.stdout)
        self.assertIn("codex hook-c/c.py 1 0 1 0 0 0 0 20", result.stdout)
        self.assertIn("unregistered:\nclaude loose/z.py", result.stdout)

    def test_missing_log_exits_two_with_unchecked(self) -> None:
        self.seed_configs()
        result = self.run_report()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unchecked: no metrics log at", result.stdout)

    def test_json_output_reports_same_data(self) -> None:
        self.seed_configs()
        self.write_rows([self.row("claude", "hook-a", "a.py", "spoke")])
        result = self.run_report("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["registered"][0]["hook"], "hook-a")
        self.assertTrue(any(row["no_record"] for row in data["registered"]))

    def test_since_filters_old_rows(self) -> None:
        self.seed_configs()
        old = self.row("claude", "hook-a", "a.py", "spoke")
        old["ts"] = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        self.write_rows([old])
        result = self.run_report("--since", "7d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude hook-a/a.py no record", result.stdout)


if __name__ == "__main__":
    unittest.main()
