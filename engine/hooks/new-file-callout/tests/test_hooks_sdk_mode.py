from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CATSTACK_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(CATSTACK_ROOT / "scripts" / "test"))

from git_test_repo import init_repo  # noqa: E402

HOOK_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"


def make_repo(new_files: list[str]) -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory()
    init_repo(tmp.name)
    for rel in new_files:
        path = Path(tmp.name) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    return tmp


def transcript_file(new_files: list[str]) -> str:
    started = time.time() - 60
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)) + ".000Z"
    lines = [
        {"type": "user", "timestamp": iso, "message": {"role": "user", "content": "finish"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"w{index}",
                        "name": "Write",
                        "input": {"file_path": rel, "content": "x"},
                    }
                    for index, rel in enumerate(new_files)
                ],
            },
        },
    ]
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        repo = make_repo(["unmentioned_helper.py"])
        transcript = transcript_file(["unmentioned_helper.py"])
        try:
            result = run_entrypoint(
                {
                    "hook_event_name": "Stop",
                    "session_id": "new-file-callout-warn",
                    "last_assistant_message": "Done.",
                    "transcript_path": transcript,
                    "cwd": repo.name,
                },
                {"CATSTACK_HOOK_MODE_NEW_FILE_CALLOUT": "warn"},
            )
        finally:
            os.unlink(transcript)
            repo.cleanup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            "unmentioned_helper.py",
            rendered["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        new_files = ["unmentioned_one.py", "scripts/unmentioned_two.py"]
        repo = make_repo(new_files)
        transcript = transcript_file(new_files)
        try:
            with tempfile.TemporaryDirectory() as metrics:
                result = run_entrypoint(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "new-file-callout-events",
                        "last_assistant_message": "Done.",
                        "transcript_path": transcript,
                        "cwd": repo.name,
                    },
                    {"CATSTACK_HOOK_METRICS_DIR": metrics},
                )
                rows = event_rows(Path(metrics))
        finally:
            os.unlink(transcript)
            repo.cleanup()

        self.assertEqual(2, result.returncode)
        self.assertEqual(2, len(rows), rows)
        self.assertEqual({"new-file-callout"}, {row["hook"] for row in rows})
        self.assertEqual(
            {"new-file-callout.unmentioned-file"},
            {row["rule_id"] for row in rows},
        )
        self.assertEqual({"stopped"}, {row["action"] for row in rows})


if __name__ == "__main__":
    unittest.main()
