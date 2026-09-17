from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse  # noqa: E402

ALL_TASKS_FIRST = "can you make all tasks use claude and local executor"


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def human(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def write_transcript(entries: list[dict]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    with handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return handle.name


@contextmanager
def isolated_hook_env(**updates: str):
    old = dict(os.environ)
    try:
        os.environ.update(updates)
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def run_claude_pretooluse(payload: dict) -> tuple[int, str, str]:
    stdin = StringIO(json.dumps(payload))
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            claude_pretooluse.main()
        except SystemExit as exc:
            return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = metrics_dir / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def blocking_payload(transcript_path: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "cat-scope-sdk-mode",
        "tool_name": "Bash",
        "transcript_path": transcript_path,
        "tool_input": {"command": fixture("update_tasks_status_in_pending_queued.txt")},
    }


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        path = write_transcript([human(ALL_TASKS_FIRST)])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with isolated_hook_env(
                    CATSTACK_HOOK_METRICS_DIR=tmp,
                    CATSTACK_HOOK_MODE_CATEGORICAL_SCOPE_GUARD="warn",
                ):
                    code, stdout, stderr = run_claude_pretooluse(blocking_payload(path))
        finally:
            os.unlink(path)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertIn(ALL_TASKS_FIRST, output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = write_transcript([human(ALL_TASKS_FIRST)])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with isolated_hook_env(CATSTACK_HOOK_METRICS_DIR=tmp):
                    code, _stdout, stderr = run_claude_pretooluse(blocking_payload(path))
                    rows = event_rows(Path(tmp))
        finally:
            os.unlink(path)

        self.assertEqual(2, code)
        self.assertIn(ALL_TASKS_FIRST, stderr)
        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("categorical-scope-guard.narrowed-mutation", finding_rows[0]["rule_id"])
        self.assertTrue(all(row["hook"] == "categorical-scope-guard" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
