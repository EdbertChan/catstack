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

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import claude_stop_check  # noqa: E402


@contextmanager
def isolated_hook_env(**updates: str):
    old = dict(os.environ)
    try:
        os.environ.update(updates)
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def run_claude_stop(payload: dict[str, object]) -> tuple[int, str, str]:
    stdin = StringIO(json.dumps(payload))
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            claude_stop_check.main()
        except SystemExit as exc:
            return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = metrics_dir / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class SdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "diu-stop-warn-override",
            "last_assistant_message": "Confirmed -- the bug is in the retry loop.",
        }

        with tempfile.TemporaryDirectory() as tmp:
            with isolated_hook_env(
                CATSTACK_HOOK_METRICS_DIR=tmp,
                CATSTACK_HOOK_MODE_DIU_STOP="warn",
            ):
                code, stdout, stderr = run_claude_stop(payload)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("confirmed", output["additionalContext"].lower())

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        message = "Confirmed. " + " ".join(["word"] * (claude_stop_check.WORD_LIMIT + 10))
        payload = {
            "hook_event_name": "Stop",
            "session_id": "diu-stop-event-rows",
            "last_assistant_message": message,
        }

        with tempfile.TemporaryDirectory() as tmp:
            with isolated_hook_env(CATSTACK_HOOK_METRICS_DIR=tmp):
                code, _stdout, stderr = run_claude_stop(payload)
                rows = event_rows(Path(tmp))

        self.assertEqual(2, code)
        self.assertIn("unverified-shaped claim", stderr.lower())
        self.assertIn("diu", stderr.lower())
        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(2, len(finding_rows))
        self.assertEqual(
            ["diu-stop.unverified-claim", "diu-stop.word-limit"],
            [row["rule_id"] for row in finding_rows],
        )
        self.assertTrue(all(row["hook"] == "diu-stop" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
