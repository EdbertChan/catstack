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
    def test_warn_override_changes_claude_stop_response(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "hedge-warn-override",
            "last_assistant_message": (
                "I changed `claude.hook.json`; it should work for the new Stop hook."
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            with isolated_hook_env(
                CATSTACK_HOOK_METRICS_DIR=tmp,
                CATSTACK_HOOK_MODE_HEDGE_RUNS_PROVE_IT="warn",
            ):
                code, stdout, stderr = run_claude_stop(payload)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("additionalContext", output)
        self.assertIn("should work", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_hook_rule_id(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "hedge-event-rows",
            "last_assistant_message": (
                "It's a zombie in the worker pool, and the hook probably needs "
                "another fix in `claude.hook.json`."
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            with isolated_hook_env(CATSTACK_HOOK_METRICS_DIR=tmp):
                code, _stdout, stderr = run_claude_stop(payload)
                rows = event_rows(Path(tmp))

        self.assertEqual(2, code)
        self.assertIn("zombie", stderr)
        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(2, len(finding_rows))
        self.assertEqual(
            [
                "hedge-runs-prove-it.live-diagnosis",
                "hedge-runs-prove-it.unverified-hedge",
            ],
            [row["rule_id"] for row in finding_rows],
        )
        self.assertTrue(all(row["hook"] == "hedge-runs-prove-it" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
