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
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_stop_check.py")


def turn_lines(ran: list[str]) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = [
        {"type": "user", "message": {"role": "user", "content": "set that up for me"}},
    ]
    for script in ran:
        lines.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Bash",
                    "input": {"command": f"bash /private/tmp/claude-501/scratchpad/{script}"},
                }],
            },
        })
    return lines


def transcript_file(lines: list[dict[str, object]]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


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


def event_rows(metrics_dir: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in Path(metrics_dir).glob("events-*.jsonl"):
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        path = transcript_file(turn_lines([]))
        try:
            with tempfile.TemporaryDirectory() as metrics:
                result = run_entrypoint(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "handoff-needs-smoke-test-warn",
                        "last_assistant_message": "! bash /tmp/demo-login.sh",
                        "transcript_path": path,
                    },
                    {
                        "CATSTACK_HOOK_METRICS_DIR": metrics,
                        "CATSTACK_HOOK_MODE_HANDOFF_NEEDS_SMOKE_TEST": "warn",
                    },
                )
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "handoff-needs-smoke-test",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = transcript_file(turn_lines([]))
        try:
            with tempfile.TemporaryDirectory() as metrics:
                result = run_entrypoint(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "handoff-needs-smoke-test-events",
                        "last_assistant_message": "! bash /tmp/one.sh\n! bash /tmp/two.sh",
                        "transcript_path": path,
                    },
                    {"CATSTACK_HOOK_METRICS_DIR": metrics},
                )
                rows = event_rows(metrics)
        finally:
            os.unlink(path)

        self.assertEqual(2, result.returncode)
        self.assertEqual(2, len(rows), rows)
        for row in rows:
            self.assertEqual("handoff-needs-smoke-test", row["hook"])
            self.assertEqual("handoff-needs-smoke-test.unrun-handoff", row["rule_id"])
            self.assertEqual("stop", row["mode"])
            self.assertEqual("registry", row["mode_source"])
            self.assertEqual("stopped", row["action"])


if __name__ == "__main__":
    unittest.main()
