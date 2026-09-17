from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse_check  # noqa: E402

TARGET = "/tmp/demo/call.html"


@contextmanager
def isolated_hook_env(**updates: str):
    old = dict(os.environ)
    try:
        os.environ.update(updates)
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


@contextmanager
def frozen_marker(*lines: str):
    marker = tempfile.NamedTemporaryFile(mode="w", suffix=".freeze", delete=False)
    marker.write("\n".join(lines) + "\n")
    marker.close()
    try:
        with patch.object(claude_pretooluse_check, "MARKER", marker.name):
            yield
    finally:
        os.unlink(marker.name)


def run_claude_pretooluse(payload: dict) -> tuple[int, str, str]:
    stdin = StringIO(json.dumps(payload))
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            claude_pretooluse_check.main()
        except SystemExit as exc:
            return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = metrics_dir / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def blocking_payload() -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "demo-freeze-sdk-mode",
        "tool_name": "Edit",
        "tool_input": {"file_path": TARGET},
    }


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_block_to_warning(self) -> None:
        with frozen_marker("/tmp/demo/"):
            with tempfile.TemporaryDirectory() as tmp:
                with isolated_hook_env(
                    CATSTACK_HOOK_METRICS_DIR=tmp,
                    CATSTACK_HOOK_MODE_DEMO_FREEZE="warn",
                ):
                    code, stdout, stderr = run_claude_pretooluse(blocking_payload())

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertIn("Demo surface frozen", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with frozen_marker("/tmp/demo/"):
            with tempfile.TemporaryDirectory() as tmp:
                with isolated_hook_env(CATSTACK_HOOK_METRICS_DIR=tmp):
                    code, _stdout, stderr = run_claude_pretooluse(blocking_payload())
                    rows = event_rows(Path(tmp))

        self.assertEqual(2, code)
        self.assertIn("Demo surface frozen", stderr)
        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("demo-freeze.frozen-path", finding_rows[0]["rule_id"])
        self.assertTrue(all(row["hook"] == "demo-freeze" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
