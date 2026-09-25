from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
ROOT = HOOK_DIR.parents[2]
ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"
FIXTURE = HERE / "fixtures" / "flip.jsonl"


def _payload(session_id: str = "session-1") -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "last_assistant_message": "Opened the PR; here is the link.",
        "transcript_path": str(FIXTURE),
        "session_id": session_id,
    }


def _registry(mode: str) -> str:
    return f"""
[hooks.verdict-flip-watch]
mode = "{mode}"
why_mode = "habit"
summary = "Notes a check that passed earlier and failed later."
enabled_by = "CATSTACK_REFLECT_ENFORCEMENT"

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
"""


class HooksSdkModeTest(unittest.TestCase):
    def run_hook(
        self,
        payload: dict[str, object],
        *,
        metrics_dir: Path,
        state_dir: Path,
        registry_mode: str = "warn",
        override_mode: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        registry_path = metrics_dir / f"hooks-{registry_mode}.toml"
        registry_path.write_text(_registry(registry_mode), encoding="utf-8")
        data = dict(payload)
        data["registry_path"] = str(registry_path)
        env = dict(
            os.environ,
            CATSTACK_REFLECT_ENFORCEMENT="1",
            CATSTACK_HOOK_METRICS_DIR=str(metrics_dir),
            VERDICT_FLIP_WATCH_STATE_DIR=str(state_dir),
            PYTHONPATH=str(ROOT),
        )
        if override_mode is not None:
            env["CATSTACK_HOOK_MODE_VERDICT_FLIP_WATCH"] = override_mode
        return subprocess.run(
            [sys.executable, str(ENTRYPOINT)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            env=env,
        )

    def test_warn_override_turns_registry_stop_into_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stop_res = self.run_hook(
                _payload("stop-session"),
                metrics_dir=root / "stop-metrics",
                state_dir=root / "stop-state",
                registry_mode="stop",
            )
            warn_res = self.run_hook(
                _payload("warn-session"),
                metrics_dir=root / "warn-metrics",
                state_dir=root / "warn-state",
                registry_mode="stop",
                override_mode="warn",
            )

        self.assertEqual(2, stop_res.returncode, stop_res.stderr)
        self.assertIn("verdict-flip-watch", stop_res.stderr)
        self.assertEqual("", stop_res.stdout)

        self.assertEqual(0, warn_res.returncode, warn_res.stderr)
        self.assertEqual("", warn_res.stderr)
        body = json.loads(warn_res.stdout)
        self.assertIn(
            "verdict-flip-watch",
            body["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics_dir = root / "metrics"
            res = self.run_hook(
                _payload("event-session"),
                metrics_dir=metrics_dir,
                state_dir=root / "state",
            )
            files = list(metrics_dir.glob("events-*.jsonl"))
            self.assertEqual(1, len(files))
            rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

        self.assertEqual(0, res.returncode, res.stderr)
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("verdict-flip-watch.stale-verdict", finding_rows[0]["rule_id"])
        self.assertEqual("verdict-flip-watch", finding_rows[0]["hook"])
        self.assertEqual("warned", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
