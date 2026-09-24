from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse.py")


def write_payload(content: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "explicit-failures-sdk-mode",
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/sample.py",
            "content": content,
        },
    }


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


def registry_with_explicit_failures_mode(directory: str, mode: str) -> str:
    path = os.path.join(directory, "hooks.toml")
    Path(path).write_text(
        textwrap.dedent(
            f"""
            [hooks.explicit-failures]
            mode = "{mode}"
            why_mode = "habit"
            summary = "Warns about code that hides errors."

            [thresholds]
            min_closed_findings = 30
            promote_max_ignore_rate = 0.02
            demote_min_ignore_rate = 0.10
            review_min_ignore_rate = 0.50
            review_min_unchecked_rate = 0.05
            followup_window_checks = 3
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return path


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_registry_stop_to_warning(self) -> None:
        content = "try:\n    run()\nexcept OSError:\n    pass\n"
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = registry_with_explicit_failures_mode(tmp, "stop")
            payload = write_payload(content) | {"registry_path": registry_path}

            stopped = run_entrypoint(payload, {"CATSTACK_HOOK_METRICS_DIR": tmp})
            warned = run_entrypoint(
                payload,
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_EXPLICIT_FAILURES": "warn",
                },
            )

        self.assertEqual(2, stopped.returncode)
        self.assertIn("explicit-failures: raise", stopped.stderr)

        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertIn("explicit-failures: raise", warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertIn(
            "explicit-failures: raise",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        content = (
            "try:\n"
            "    read_one()\n"
            "except OSError:\n"
            "    pass\n"
            "try:\n"
            "    read_two()\n"
            "except ValueError:\n"
            "    pass\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_entrypoint(
                write_payload(content),
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_EXPLICIT_FAILURES": "warn",
                },
            )
            rows = [
                json.loads(line)
                for file in Path(tmp).glob("events-*.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(rows))
        for row in rows:
            self.assertEqual("explicit-failures", row["hook"])
            self.assertEqual("explicit-failures.python-except", row["rule_id"])
            self.assertEqual("warn", row["mode"])
            self.assertEqual("override", row["mode_source"])
            self.assertEqual("warned", row["action"])


if __name__ == "__main__":
    unittest.main()
