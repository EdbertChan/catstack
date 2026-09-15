import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.hooks._sdk.events import append_events
from engine.hooks._sdk.finding import Finding
from engine.hooks._sdk.modes import effective_mode
from engine.hooks._sdk.runtime import run_hook


FINDINGS = [
    Finding("rule.one", "subject one", "first message", "first evidence"),
    Finding("rule.two", "subject two", "second message", "second evidence"),
]

EXPECTED_FIELDS = {
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
}


def read_rows(directory: Path) -> list[dict]:
    files = list(directory.glob("events-*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


class EventTests(unittest.TestCase):
    def test_each_finding_writes_one_schema_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmpdir}):
                append_events(
                    "repeat-error-stop",
                    "codex",
                    {"session_id": "session-123"},
                    FINDINGS,
                    "stop",
                    "registry",
                    17,
                )
            rows = read_rows(Path(tmpdir))

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["rule_id"] for row in rows}, {"rule.one", "rule.two"})
        self.assertEqual(rows[0].keys(), EXPECTED_FIELDS)
        for row in rows:
            self.assertEqual(row["harness"], "codex")
            self.assertEqual(row["session_id"], "session-123")
            self.assertEqual(row["hook"], "repeat-error-stop")
            self.assertEqual(row["mode"], "stop")
            self.assertEqual(row["mode_source"], "registry")
            self.assertEqual(row["action"], "stopped")
            self.assertEqual(row["duration_ms"], 17)
            self.assertRegex(row["finding_id"], r"^[0-9a-f]{32}$")
            self.assertRegex(row["subject_hash"], r"^[0-9a-f]{64}$")
            self.assertTrue(row["ts"])
            self.assertTrue(row["machine"])

    def test_no_findings_writes_one_silent_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmpdir}):
                append_events("diu-stop", "claude", {"sessionId": "abc"}, [], "warn", "registry", 3)
            rows = read_rows(Path(tmpdir))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "silent")
        self.assertEqual(rows[0]["rule_id"], "")
        self.assertEqual(rows[0]["session_id"], "abc")

    def test_effective_mode_reads_registry(self):
        self.assertEqual(effective_mode("repeat-error-stop", {}), ("stop", "registry"))

    def test_effective_mode_uses_per_machine_override(self):
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_REPEAT_ERROR_STOP": "warn"}):
            self.assertEqual(effective_mode("repeat-error-stop", {}), ("warn", "override"))

    def test_failed_event_write_reports_error_and_runtime_still_outputs_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_metrics_dir = Path(tmpdir) / "not-a-directory"
            bad_metrics_dir.write_text("occupied", encoding="utf-8")
            event = {"session_id": "s", "hook_event_name": "PreToolUse"}
            stdin = io.StringIO(json.dumps(event))
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch.dict(os.environ, {
                "CATSTACK_HOOK_MODE_REPEAT_ERROR_STOP": "stop",
                "CATSTACK_HOOK_METRICS_DIR": str(bad_metrics_dir),
            }):
                with patch("sys.stdin", stdin), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        run_hook("repeat-error-stop", "codex", lambda _event: [FINDINGS[0]])

        self.assertEqual(raised.exception.code, 0)
        err_lines = [line for line in stderr.getvalue().splitlines() if line]
        self.assertEqual(len(err_lines), 1)
        self.assertTrue(err_lines[0].startswith("catstack-hook-error"))
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(data["hookSpecificOutput"]["permissionDecisionReason"], "first message")


if __name__ == "__main__":
    unittest.main()
