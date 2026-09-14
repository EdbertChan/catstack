from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import events
import followup
import runtime
from finding import Finding


class FollowupTest(unittest.TestCase):
    def test_refire_on_same_subject_within_window_closes_older_finding_as_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self._run(tmp, "session-ignored", [self._finding()])
            self._run(tmp, "session-ignored", [])
            self._run(tmp, "session-ignored", [])
            self._run(tmp, "session-ignored", [self._finding()])
            rows = self._rows(tmp)

        first_finding_id = self._finding_rows(rows)[0]["finding_id"]
        self.assertTrue(
            any(
                row.get("action") == "followup"
                and row.get("finding_id") == first_finding_id
                and row.get("outcome") == "ignored"
                for row in rows
            ),
            rows,
        )

    def test_no_refire_within_window_closes_finding_as_acted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self._run(tmp, "session-acted", [self._finding()])
            self._run(tmp, "session-acted", [])
            self._run(tmp, "session-acted", [])
            self._run(tmp, "session-acted", [])
            rows = self._rows(tmp)

        first_finding_id = self._finding_rows(rows)[0]["finding_id"]
        self.assertTrue(
            any(
                row.get("action") == "followup"
                and row.get("finding_id") == first_finding_id
                and row.get("outcome") == "acted"
                for row in rows
            ),
            rows,
        )

    def test_lower_override_mode_on_same_subject_closes_older_finding_as_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self._run(tmp, "session-overridden", [self._finding()], hook="diu-stop")
            with mock.patch.dict(os.environ, {"CATSTACK_HOOK_MODE_DIU_STOP": "warn"}, clear=False):
                self._run(tmp, "session-overridden", [self._finding()], hook="diu-stop")
            rows = self._rows(tmp)

        first_finding_id = self._finding_rows(rows)[0]["finding_id"]
        self.assertTrue(
            any(
                row.get("action") == "followup"
                and row.get("finding_id") == first_finding_id
                and row.get("outcome") == "overridden"
                for row in rows
            ),
            rows,
        )

    def test_session_end_closes_remaining_open_findings_as_acted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self._run(tmp, "session-end", [self._finding()])
            self._run(tmp, "session-end", [], hook_event_name="SessionEnd")
            rows = self._rows(tmp)

        first_finding_id = self._finding_rows(rows)[0]["finding_id"]
        self.assertTrue(
            any(
                row.get("action") == "followup"
                and row.get("finding_id") == first_finding_id
                and row.get("outcome") == "acted"
                for row in rows
            ),
            rows,
        )

    def test_unreadable_state_writes_unchecked_followup_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            event = {"hook_event_name": "PostToolUse", "session_id": "session-corrupt"}
            state_path = followup._state_path(event)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{broken", encoding="utf-8")
            self._run(tmp, "session-corrupt", [])
            rows = self._rows(tmp)

        self.assertTrue(
            any(
                row.get("action") == "followup"
                and row.get("outcome") == "unchecked"
                for row in rows
            ),
            rows,
        )

    def test_prune_deletes_event_files_older_than_30_days_at_most_once_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            old = Path(tmp) / "events-2026-08-14.jsonl"
            boundary = Path(tmp) / "events-2026-08-15.jsonl"
            old.write_text("{}\n", encoding="utf-8")
            boundary.write_text("{}\n", encoding="utf-8")

            events.prune_old_event_files(today=date(2026, 9, 14))
            self.assertFalse(old.exists())
            self.assertTrue(boundary.exists())

            second_old = Path(tmp) / "events-2026-08-01.jsonl"
            second_old.write_text("{}\n", encoding="utf-8")
            events.prune_old_event_files(today=date(2026, 9, 14))
            self.assertTrue(second_old.exists())

            events.prune_old_event_files(today=date(2026, 9, 15))
            self.assertFalse(second_old.exists())

    def test_prune_failure_prints_catstack_hook_error_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            old = Path(tmp) / "events-2026-08-01.jsonl"
            old.write_text("{}\n", encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(events.Path, "unlink", side_effect=OSError("blocked")):
                events.prune_old_event_files(stderr=err, today=date(2026, 9, 14))

        lines = err.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("catstack-hook-error metrics: event prune failed"))

    def _run(
        self,
        tmp: str,
        session_id: str,
        findings: list[Finding],
        hook_event_name: str = "PostToolUse",
        hook: str = "agent-relay-attribution",
    ) -> None:
        event = {"hook_event_name": hook_event_name, "session_id": session_id}
        with self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook(hook, "codex", lambda _event: findings)
        self.assertEqual(0, caught.exception.code)

    def _finding(self) -> Finding:
        return Finding("demo.rule", "file:app.py", "Demo message", "demo evidence")

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

    def _finding_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            row
            for row in rows
            if row.get("action") in {"stopped", "warned"}
            and row.get("rule_id") == "demo.rule"
        ]


if __name__ == "__main__":
    unittest.main()
