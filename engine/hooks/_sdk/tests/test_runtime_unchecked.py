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

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import runtime
from finding import Finding

STOP_EVENT = {"hook_event_name": "Stop", "session_id": "session-unchecked", "model": "claude-sonnet-5"}
UNCHECKED = Finding(
    "technical-writing-guard.unchecked",
    "technical writing grader",
    "The document check could not load. Leave the reply unchecked.",
    "grade_prose import failed",
)
REAL = Finding("technical-writing-guard.other", "reply:abc", "Shorten the sentence.", "41 words")


class RuntimeUncheckedTest(unittest.TestCase):
    def _run(self, findings: list[Finding]) -> tuple[int, str, list[dict]]:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": tmp, "CATSTACK_HOOK_MODE_TECHNICAL_WRITING_GUARD": "stop"},
            clear=False,
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(STOP_EVENT))):
                with self.assertRaises(SystemExit) as caught:
                    runtime.run_hook("technical-writing-guard", "claude", lambda _event: findings)
            rows = []
            for events_file in sorted(Path(tmp).glob("events-*.jsonl")):
                rows.extend(json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip())
        return int(caught.exception.code or 0), err.getvalue(), rows

    def test_unchecked_rule_id_never_exits_2_and_writes_an_unchecked_row(self) -> None:
        code, _stderr, rows = self._run([UNCHECKED])
        self.assertEqual(0, code)
        self.assertEqual(["unchecked"], [row["action"] for row in rows])
        self.assertEqual("technical-writing-guard.unchecked", rows[0]["rule_id"])

    def test_other_rule_id_on_stop_still_exits_2(self) -> None:
        code, stderr, rows = self._run([REAL])
        self.assertEqual(2, code)
        self.assertIn("Shorten the sentence.", stderr)
        self.assertEqual(["stopped"], [row["action"] for row in rows])

    def test_unchecked_beside_a_real_finding_blocks_on_the_real_one_only(self) -> None:
        code, stderr, rows = self._run([UNCHECKED, REAL])
        self.assertEqual(2, code)
        self.assertNotIn("could not load", stderr)
        self.assertEqual({"unchecked", "stopped"}, {row["action"] for row in rows})


if __name__ == "__main__":
    unittest.main()
