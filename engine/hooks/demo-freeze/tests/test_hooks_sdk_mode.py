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
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse_check.py")


def write_marker(lines: list[str]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".demo-freeze", delete=False, encoding="utf-8")
    with handle:
        handle.write("\n".join(lines) + "\n")
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
        marker = write_marker(["/tmp/demo/call.html"])
        try:
            result = run_entrypoint(
                {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/demo/call.html"}},
                {
                    "DEMO_FREEZE_FILE": marker,
                    "CATSTACK_HOOK_MODE_DEMO_FREEZE": "warn",
                },
            )
        finally:
            os.unlink(marker)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "Demo surface frozen",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_mode_stop_still_blocks_by_default(self) -> None:
        marker = write_marker(["/tmp/demo/call.html"])
        try:
            result = run_entrypoint(
                {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/demo/call.html"}},
                {"DEMO_FREEZE_FILE": marker},
            )
        finally:
            os.unlink(marker)

        self.assertEqual(2, result.returncode)
        self.assertIn("Demo surface frozen", result.stderr)

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        marker = write_marker(["/tmp/demo/call.html"])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_entrypoint(
                    {
                        "tool_name": "Edit",
                        "session_id": "demo-freeze-sdk-mode",
                        "tool_input": {"file_path": "/tmp/demo/call.html"},
                    },
                    {
                        "DEMO_FREEZE_FILE": marker,
                        "CATSTACK_HOOK_METRICS_DIR": tmp,
                        "CATSTACK_HOOK_MODE_DEMO_FREEZE": "warn",
                    },
                )
                rows = [
                    json.loads(line)
                    for file in Path(tmp).glob("events-*.jsonl")
                    for line in file.read_text(encoding="utf-8").splitlines()
                ]
        finally:
            os.unlink(marker)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("demo-freeze", rows[0]["hook"])
        self.assertEqual("demo-freeze.frozen-path", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
