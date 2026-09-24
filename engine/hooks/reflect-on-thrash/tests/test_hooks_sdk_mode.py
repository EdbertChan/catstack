from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
REPO_ROOT = HOOK_DIR.parents[1]
ENTRYPOINT = HOOK_DIR / "claude_stop_reflect.py"
FIXTURE = REPO_ROOT / "skills" / "reflect" / "scripts" / "tests" / "fixtures" / "token_thrash_session.jsonl"


def registry_with_reflect_mode(directory: str, mode: str) -> str:
    path = Path(directory) / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [hooks.reflect-on-thrash]
            mode = "{mode}"
            why_mode = "habit"
            summary = "Suggests a reflect pass when a session goes in circles."
            enabled_by = "CATSTACK_REFLECT_ENFORCEMENT"

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
    return str(path)


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


class SdkModeTest(unittest.TestCase):
    def test_warn_override_turns_stop_response_into_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = registry_with_reflect_mode(tmp, "stop")
            payload = {
                "hook_event_name": "Stop",
                "session_id": "reflect-on-thrash-sdk-mode",
                "transcript_path": str(FIXTURE),
                "registry_path": registry_path,
            }
            stopped = run_entrypoint(
                payload,
                {
                    "CATSTACK_REFLECT_ENFORCEMENT": "1",
                    "CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "metrics-stop"),
                    "REFLECT_ON_THRASH_STATE_DIR": str(Path(tmp) / "state-stop"),
                },
            )
            warned = run_entrypoint(
                payload,
                {
                    "CATSTACK_REFLECT_ENFORCEMENT": "1",
                    "CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "metrics-warn"),
                    "REFLECT_ON_THRASH_STATE_DIR": str(Path(tmp) / "state-warn"),
                    "CATSTACK_HOOK_MODE_REFLECT_ON_THRASH": "warn",
                },
            )

        self.assertEqual(2, stopped.returncode)
        self.assertIn("Intervention flagged", stopped.stderr)
        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertEqual("", warned.stderr)
        rendered = json.loads(warned.stdout)
        self.assertIn(
            "Intervention flagged",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_entrypoint(
                {
                    "hook_event_name": "Stop",
                    "session_id": "reflect-on-thrash-sdk-events",
                    "transcript_path": str(FIXTURE),
                },
                {
                    "CATSTACK_REFLECT_ENFORCEMENT": "1",
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "REFLECT_ON_THRASH_STATE_DIR": str(Path(tmp) / "state"),
                    "CATSTACK_HOOK_MODE_REFLECT_ON_THRASH": "warn",
                },
            )
            rows = [
                json.loads(line)
                for file in Path(tmp).glob("events-*.jsonl")
                for line in file.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("reflect-on-thrash", rows[0]["hook"])
        self.assertEqual("reflect-on-thrash.intervention-must-automate", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
