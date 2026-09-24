from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse.py"


def bash_payload(command: str, session_id: str = "publish-act-guard-test") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "subagent_id": "a4b7b959ce73515c9",
    }


def write_live_cache(tmpdir: Path) -> None:
    cache = tmpdir / "publish-act-guard-liveness.json"
    cache.write_text(json.dumps({"state": "live", "at": time.time()}), encoding="utf-8")


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
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as metrics:
            write_live_cache(Path(tmp))
            result = run_hook(
                bash_payload("git push -u origin HEAD"),
                {
                    "TMPDIR": tmp,
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                    "CATSTACK_HOOK_MODE_PUBLISH_ACT_GUARD": "warn",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertIn(
            "publish-act-guard",
            body["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual("", result.stderr)

    def test_writes_one_event_row_per_finding_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as metrics:
            write_live_cache(Path(tmp))
            result = run_hook(
                bash_payload("git push -u origin HEAD", session_id="publish-act-guard-events"),
                {
                    "TMPDIR": tmp,
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                },
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("publish-act-guard", rows[0]["hook"])
        self.assertEqual("publish-act-guard.subagent-publish", rows[0]["rule_id"])
        self.assertEqual("stopped", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
