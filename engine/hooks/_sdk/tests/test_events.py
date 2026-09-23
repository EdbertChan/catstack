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
from events import write_events, write_stage_event
from finding import Finding
from modes import effective_mode


class EventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = [
            Finding("demo.first", "cmd:pytest", "First message", "first evidence"),
            Finding("demo.second", "file:app.py", "Second message", "second evidence"),
        ]

    def test_each_finding_writes_one_schema_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            write_events(
                "repeat-error-stop",
                "codex",
                {"session_id": "session-1"},
                self.findings,
                "stop",
                "registry",
                17,
            )
            rows = self._rows(tmp)

        self.assertEqual(2, len(rows))
        for row, finding in zip(rows, self.findings):
            with self.subTest(rule_id=finding.rule_id):
                self.assertEqual(
                    {
                        "schema",
                        "ts",
                        "machine",
                        "harness",
                        "session_id",
                        "hook",
                        "rule_id",
                        "subject_hash",
                        "mode",
                        "mode_source",
                        "action",
                        "finding_id",
                        "duration_ms",
                    },
                    set(row),
                )
                self.assertEqual("catstack.hook_event.v1", row["schema"])
                self.assertEqual("codex", row["harness"])
                self.assertEqual("session-1", row["session_id"])
                self.assertEqual("repeat-error-stop", row["hook"])
                self.assertEqual(finding.rule_id, row["rule_id"])
                self.assertEqual("stop", row["mode"])
                self.assertEqual("registry", row["mode_source"])
                self.assertEqual("stopped", row["action"])
                self.assertEqual(17, row["duration_ms"])
                self.assertRegex(row["subject_hash"], r"^[0-9a-f]{64}$")
                self.assertRegex(row["finding_id"], r"^[0-9a-f]{32}$")

    def test_no_findings_writes_one_silent_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            write_events("diu-stop", "claude", {"sessionId": "session-2"}, [], "warn", "override", 0)
            rows = self._rows(tmp)

        self.assertEqual(1, len(rows))
        self.assertEqual("silent", rows[0]["action"])
        self.assertEqual("", rows[0]["rule_id"])
        self.assertEqual("session-2", rows[0]["session_id"])

    def test_event_write_failure_prints_one_hook_error_line_and_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "not-a-dir"
            metrics_path.write_text("occupied", encoding="utf-8")
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": str(metrics_path)}, clear=False):
                write_events("scope-lock", "cursor", {}, self.findings[:1], "warn", "registry", 3, err)

        lines = err.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("catstack-hook-error"))

    def test_effective_mode_reads_registry_and_environment_override(self) -> None:
        self.assertEqual(("stop", "registry"), effective_mode("diu-stop", {}))
        with mock.patch.dict(os.environ, {"CATSTACK_HOOK_MODE_DIU_STOP": "warn"}, clear=False):
            self.assertEqual(("warn", "override"), effective_mode("diu-stop", {}))

    def test_runtime_writes_events_prints_rendered_response_and_exits_with_code(self) -> None:
        event = {"hook_event_name": "Stop", "session_id": "session-3"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": tmp, "CATSTACK_HOOK_MODE_DIU_STOP": "stop"},
            clear=False,
        ), self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook("diu-stop", "claude", lambda _event: self.findings[:1])
            rows = self._rows(tmp)
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()

        self.assertEqual(2, caught.exception.code)
        self.assertEqual("", stdout)
        self.assertIn("First message", stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("stopped", rows[0]["action"])

    def test_runtime_detector_exception_prints_error_and_allows(self) -> None:
        event = {"hook_event_name": "PreToolUse", "session_id": "session-4"}

        def broken(_event: dict[str, object]) -> list[Finding]:
            raise RuntimeError("broken detector")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ), self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook("diu-stop", "codex", broken)
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            rows = self._rows(tmp)

        self.assertEqual(0, caught.exception.code)
        self.assertEqual("", stdout)
        self.assertIn("catstack-hook-error diu-stop: RuntimeError: broken detector", stderr)
        self.assertEqual("crashed", rows[0]["action"])
        self.assertEqual("runtime", rows[0]["mode_source"])

    def test_runtime_event_write_failure_still_prints_rendered_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "not-a-dir"
            metrics_path.write_text("occupied", encoding="utf-8")
            event = {"hook_event_name": "PostToolUse", "session_id": "session-5"}
            with mock.patch.dict(
                os.environ,
                {"CATSTACK_HOOK_METRICS_DIR": str(metrics_path), "CATSTACK_HOOK_MODE_DIU_STOP": "warn"},
                clear=False,
            ), self._stdio(json.dumps(event)):
                with self.assertRaises(SystemExit) as caught:
                    runtime.run_hook("diu-stop", "codex", lambda _event: self.findings[:1])
                stdout = sys.stdout.getvalue()
                stderr = sys.stderr.getvalue()

        self.assertEqual(0, caught.exception.code)
        self.assertTrue(stderr.startswith("catstack-hook-error"))
        self.assertIn("First message", json.loads(stdout)["hookSpecificOutput"]["additionalContext"])

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

    def test_stage_event_carries_its_reason_and_no_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self.assertTrue(
                write_stage_event("demo", "claude", "session-1", "judge_skipped", "already_prompted", "job-1")
            )
            rows = self._rows(tmp)

        self.assertEqual(1, len(rows))
        self.assertEqual("judge_skipped", rows[0]["action"])
        self.assertEqual("already_prompted", rows[0]["reason"])
        self.assertEqual("stage", rows[0]["mode_source"])
        self.assertEqual("job-1", rows[0]["finding_id"])
        self.assertEqual("", rows[0]["rule_id"])

    def _rows(self, directory: str) -> list[dict[str, object]]:
        files = list(Path(directory).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
