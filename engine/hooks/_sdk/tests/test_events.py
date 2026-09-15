from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch
import sys
import tempfile
import unittest


SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import events  # noqa: E402
from finding import Finding  # noqa: E402
import runtime  # noqa: E402


def sample_finding(rule_id: str = "demo.rule", subject: str = "/tmp/a.py") -> Finding:
    return Finding(rule_id, subject, "Message", "Evidence")


class EventsTest(unittest.TestCase):
    def test_each_finding_writes_one_event_row_with_required_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
            os.environ["CATSTACK_HOOK_METRICS_DIR"] = tmp
            try:
                events.append_events(
                    event={"session_id": "s-1"},
                    harness="codex",
                    hook="demo-hook",
                    mode="stop",
                    mode_source="registry",
                    findings=[sample_finding("r1", "subject-a"), sample_finding("r2", "subject-b")],
                    duration_ms=17,
                )
            finally:
                if old_dir is None:
                    os.environ.pop("CATSTACK_HOOK_METRICS_DIR", None)
                else:
                    os.environ["CATSTACK_HOOK_METRICS_DIR"] = old_dir

            today = datetime.now(timezone.utc).date().isoformat()
            rows = [
                json.loads(line)
                for line in (Path(tmp) / f"events-{today}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(2, len(rows))
        required = {
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
        for row in rows:
            self.assertEqual(required, set(row))
            self.assertEqual("catstack.hook.finding.v1", row["schema"])
            self.assertEqual("codex", row["harness"])
            self.assertEqual("s-1", row["session_id"])
            self.assertEqual("demo-hook", row["hook"])
            self.assertEqual("stop", row["mode"])
            self.assertEqual("registry", row["mode_source"])
            self.assertEqual("stopped", row["action"])
            self.assertEqual(32, len(row["finding_id"]))
            self.assertEqual(64, len(row["subject_hash"]))
            self.assertEqual(17, row["duration_ms"])
        self.assertEqual(["r1", "r2"], [row["rule_id"] for row in rows])
        self.assertNotEqual(rows[0]["subject_hash"], rows[1]["subject_hash"])

    def test_no_findings_writes_one_silent_row(self) -> None:
        rows = events.event_rows(
            event={"sessionId": "camel-session"},
            harness="claude",
            hook="demo-hook",
            mode="warn",
            mode_source="override",
            findings=[],
            duration_ms=1,
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("silent", rows[0]["action"])
        self.assertEqual("", rows[0]["rule_id"])
        self.assertEqual("camel-session", rows[0]["session_id"])

    def test_failed_event_write_prints_error_and_does_not_raise(self) -> None:
        err = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(events, "metrics_dir", return_value=Path(tmp)):
                with patch("pathlib.Path.open", side_effect=OSError("disk full")):
                    with redirect_stderr(err):
                        events.append_events(
                            event={},
                            harness="cursor",
                            hook="demo-hook",
                            mode="warn",
                            mode_source="registry",
                            findings=[sample_finding()],
                            duration_ms=2,
                        )
        self.assertTrue(err.getvalue().startswith("catstack-hook-error"))

    def test_runtime_still_emits_response_when_event_write_fails(self) -> None:
        stdin = StringIO(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s-2"}))
        stdout = StringIO()
        stderr = StringIO()

        def detect(event: dict[str, object]) -> list[Finding]:
            self.assertEqual("s-2", event["session_id"])
            return [sample_finding()]

        with patch.object(sys, "stdin", stdin):
            with patch.object(runtime, "append_events", side_effect=lambda **_: print("catstack-hook-error events: nope", file=sys.stderr)):
                with patch.object(runtime, "effective_mode", return_value=("stop", "registry")):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            runtime.run_hook("demo-hook", "codex", detect)

        self.assertEqual(0, caught.exception.code)
        body = json.loads(stdout.getvalue())
        self.assertEqual("deny", body["hookSpecificOutput"]["permissionDecision"])
        self.assertTrue(stderr.getvalue().startswith("catstack-hook-error"))

    def test_detector_exception_prints_error_and_lets_action_through(self) -> None:
        stdin = StringIO(json.dumps({"hook_event_name": "PreToolUse"}))
        stdout = StringIO()
        stderr = StringIO()

        def detect(event: dict[str, object]) -> list[Finding]:
            raise RuntimeError("boom")

        with patch.object(sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook("demo-hook", "codex", detect)

        self.assertEqual(0, caught.exception.code)
        self.assertEqual("", stdout.getvalue())
        self.assertTrue(stderr.getvalue().startswith("catstack-hook-error demo-hook"))


if __name__ == "__main__":
    unittest.main()
