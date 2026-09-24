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


def edit_payload(session_id: str = "no-comments-sdk-mode") -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/repo/hook.py",
            "old_string": "x",
            "new_string": "x = 1\n# explain the branch\n",
        },
    }


def run_hook(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
        with tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                edit_payload(),
                {
                    "CATSTACK_HOOK_MODE_NO_COMMENTS": "warn",
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        rendered = json.loads(result.stdout)
        self.assertIn(
            "no-comments",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_writes_one_event_row_per_finding_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                edit_payload(session_id="no-comments-events"),
                {"CATSTACK_HOOK_METRICS_DIR": metrics},
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["hook"], "no-comments")
        self.assertEqual(rows[0]["rule_id"], "no-comments.comment-line")
        self.assertEqual(rows[0]["mode"], "stop")
        self.assertEqual(rows[0]["mode_source"], "registry")
        self.assertEqual(rows[0]["action"], "stopped")


if __name__ == "__main__":
    unittest.main()
