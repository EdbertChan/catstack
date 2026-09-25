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
ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"
RULE_ID = "handoff-needs-smoke-test.unrun-script"


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.pop("CATSTACK_HOOK_MODE_HANDOFF_NEEDS_SMOKE_TEST", None)
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def transcript_path(directory: str, ran: list[str]) -> str:
    lines = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"run-{name}",
                        "name": "Bash",
                        "input": {"command": f"bash /tmp/{name}"},
                    }
                ],
            },
        }
        for name in ran
    ]
    path = Path(directory) / "session.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return str(path)


class SdkModeTest(unittest.TestCase):
    def payload(self, directory: str, reply: str, ran: list[str] | None = None) -> dict[str, object]:
        return {
            "hook_event_name": "Stop",
            "session_id": "handoff-needs-smoke-test-sdk-mode",
            "transcript_path": transcript_path(directory, ran or []),
            "last_assistant_message": reply,
        }

    def test_warn_override_changes_stop_to_warning(self) -> None:
        reply = "! bash /tmp/demo-login.sh\n"
        with tempfile.TemporaryDirectory() as tmp:
            stop_result = run_entrypoint(
                self.payload(tmp, reply),
                {"CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "stop-metrics")},
            )
            warn_result = run_entrypoint(
                self.payload(tmp, reply),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "warn-metrics"),
                    "CATSTACK_HOOK_MODE_HANDOFF_NEEDS_SMOKE_TEST": "warn",
                },
            )

        self.assertEqual(2, stop_result.returncode, stop_result.stderr)
        self.assertIn("handoff-needs-smoke-test", stop_result.stderr)
        self.assertEqual("", stop_result.stdout)
        self.assertEqual(0, warn_result.returncode, warn_result.stderr)
        self.assertEqual("", warn_result.stderr)
        rendered = json.loads(warn_result.stdout)
        self.assertIn("handoff-needs-smoke-test", rendered["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        reply = "! bash /tmp/stage-one.sh\n\n! bash /tmp/stage-two.sh\n"
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            result = run_entrypoint(
                self.payload(tmp, reply),
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_HANDOFF_NEEDS_SMOKE_TEST": "warn",
                },
            )
            rows = [
                json.loads(line)
                for path in metrics.glob("events-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(rows))
        self.assertEqual([RULE_ID, RULE_ID], [row["rule_id"] for row in rows])
        self.assertTrue(all(row["hook"] == "handoff-needs-smoke-test" for row in rows))
        self.assertTrue(all(row["mode"] == "warn" for row in rows))
        self.assertTrue(all(row["mode_source"] == "override" for row in rows))
        self.assertTrue(all(row["action"] == "warned" for row in rows))


if __name__ == "__main__":
    unittest.main()
