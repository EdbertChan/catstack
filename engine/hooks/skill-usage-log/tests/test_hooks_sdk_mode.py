from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse_log.py"


def tool_payload(tool_name: str, tool_input: object) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "skill-usage-log-sdk-test",
        "tool_name": tool_name,
        "tool_input": tool_input,
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
    def test_mode_override_warn_changes_silent_result_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as metrics_dir:
            env = os.environ.copy()
            env.update(
                {
                    "CATSTACK_HOOK_METRICS_DIR": metrics_dir,
                    "CATSTACK_HOOK_MODE_SKILL_USAGE_LOG": "warn",
                }
            )
            result = run_hook(tool_payload("Skill", {"skill": "diu"}), env)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("diu", output["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as metrics_dir:
            env = os.environ.copy()
            env.pop("CATSTACK_HOOK_MODE_SKILL_USAGE_LOG", None)
            env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
            result = run_hook(
                tool_payload(
                    "Read",
                    {
                        "paths": [
                            "/tmp/.claude/skills/diu/SKILL.md",
                            "/tmp/.claude/skills/reflect/SKILL.md",
                        ]
                    },
                ),
                env,
            )
            rows = self._event_rows(metrics_dir)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual(2, len(rows))
        self.assertEqual(
            ["skill-usage-log.read", "skill-usage-log.read"],
            [row["rule_id"] for row in rows],
        )
        self.assertTrue(all(row["hook"] == "skill-usage-log" for row in rows))

    def _event_rows(self, metrics_dir: str) -> list[dict[str, object]]:
        files = list(Path(metrics_dir).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
