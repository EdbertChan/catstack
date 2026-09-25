from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
CATSTACK_ROOT = HERE.parents[3]
sys.path.insert(0, str(CATSTACK_ROOT / "scripts" / "test"))
ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"

from git_test_repo import init_repo  # noqa: E402


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
    def payload(self, directory: str) -> tuple[dict[str, object], tempfile.TemporaryDirectory[str], str]:
        repo = tempfile.TemporaryDirectory()
        init_repo(repo.name)
        path = Path(repo.name) / "unmentioned_helper.py"
        path.write_text("x\n", encoding="utf-8")
        started = time.time() - 60
        iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)) + ".000Z"
        transcript = Path(directory) / "session.jsonl"
        lines = [
            {"type": "user", "timestamp": iso, "message": {"role": "user", "content": "finish"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "w1",
                            "name": "Write",
                            "input": {"file_path": "unmentioned_helper.py", "content": "x\n"},
                        }
                    ],
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
        payload = {
            "hook_event_name": "Stop",
            "session_id": "new-file-callout-sdk-mode",
            "transcript_path": str(transcript),
            "last_assistant_message": "Done. Tests passed.",
            "cwd": repo.name,
        }
        return payload, repo, "unmentioned_helper.py"

    def test_warn_override_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload, repo, filename = self.payload(tmp)
            try:
                result = run_entrypoint(
                    payload,
                    {
                        "CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "metrics"),
                        "CATSTACK_HOOK_MODE_NEW_FILE_CALLOUT": "warn",
                    },
                )
            finally:
                repo.cleanup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(filename, rendered["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            payload, repo, _filename = self.payload(tmp)
            try:
                result = run_entrypoint(
                    payload,
                    {
                        "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                        "CATSTACK_HOOK_MODE_NEW_FILE_CALLOUT": "warn",
                    },
                )
            finally:
                repo.cleanup()
            rows = [
                json.loads(line)
                for path in metrics.glob("events-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("new-file-callout", rows[0]["hook"])
        self.assertEqual("new-file-callout.unnamed-new-file", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
