from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOKS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS_DIR))

import claude_stop_check  # noqa: E402


UNPROVEN_LIVE_CLAIM = (
    "The Linear-sync worker is done and shipped -- it passed its unit tests and "
    "shows up registered in the settings panel UI."
)


class SdkModeTest(unittest.TestCase):
    def test_warn_override_turns_stop_response_into_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "CATSTACK_HOOK_METRICS_DIR": tmp,
                "CATSTACK_HOOK_MODE_PROVE_IT_SHIP_GATE": "warn",
            },
            clear=False,
        ), self._stdio(json.dumps(self._event())):
            with self.assertRaises(SystemExit) as caught:
                claude_stop_check.main()
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            rows = self._rows(tmp)

        self.assertEqual(0, caught.exception.code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        self.assertIn(
            "prove-it-ship-gate",
            body["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("warned", rows[0]["action"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual(
            "prove-it-ship-gate.unproven-live-claim",
            rows[0]["rule_id"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "CATSTACK_HOOK_METRICS_DIR": tmp,
                "CATSTACK_HOOK_MODE_PROVE_IT_SHIP_GATE": "stop",
            },
            clear=False,
        ), self._stdio(json.dumps(self._event())):
            with self.assertRaises(SystemExit):
                claude_stop_check.main()
            rows = self._rows(tmp)

        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(1, len(rows))
        self.assertEqual(1, len(finding_rows))
        self.assertEqual(
            "prove-it-ship-gate.unproven-live-claim",
            finding_rows[0]["rule_id"],
        )
        self.assertEqual("prove-it-ship-gate", finding_rows[0]["hook"])

    def _event(self) -> dict[str, object]:
        return {
            "hook_event_name": "Stop",
            "session_id": "prove-it-ship-gate-test",
            "last_assistant_message": UNPROVEN_LIVE_CLAIM,
        }

    @contextlib.contextmanager
    def _stdio(self, stdin_text: str):
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdin = io.StringIO(stdin_text)
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            yield
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _rows(self, directory: str) -> list[dict[str, object]]:
        files = list(Path(directory).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
