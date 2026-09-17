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
FIXTURES = os.path.join(HERE, "fixtures")
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse.py")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def human(text: str) -> dict[str, object]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def write_transcript(entries: list[dict[str, object]]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    with handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return handle.name


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


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        path = write_transcript([human("can you make all tasks use claude and local executor")])
        try:
            result = run_entrypoint(
                {
                    "tool_name": "Bash",
                    "hook_event_name": "PreToolUse",
                    "transcript_path": path,
                    "tool_input": {"command": fixture("update_tasks_status_in_pending_queued.txt")},
                },
                {"CATSTACK_HOOK_MODE_CATEGORICAL_SCOPE_GUARD": "warn"},
            )
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "categorical-scope-guard",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = write_transcript([human("can you make all tasks use claude and local executor")])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_entrypoint(
                    {
                        "tool_name": "Bash",
                        "hook_event_name": "PreToolUse",
                        "session_id": "categorical-scope-guard-sdk-mode",
                        "transcript_path": path,
                        "tool_input": {"command": fixture("update_tasks_status_in_pending_queued.txt")},
                    },
                    {
                        "CATSTACK_HOOK_METRICS_DIR": tmp,
                        "CATSTACK_HOOK_MODE_CATEGORICAL_SCOPE_GUARD": "warn",
                    },
                )
                rows = [
                    json.loads(line)
                    for file in Path(tmp).glob("events-*.jsonl")
                    for line in file.read_text(encoding="utf-8").splitlines()
                ]
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("categorical-scope-guard", rows[0]["hook"])
        self.assertEqual("categorical-scope-guard.partial-status-filter", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
