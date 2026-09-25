from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import claude_post_tool_batch  # noqa: E402
import detect  # noqa: E402


REASON = "PreToolUse:Bash hook error: repeat-deny-stop test deny\n"


class SdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="repeat-deny-stop-sdk-test-")
        self.state_patch = patch.object(detect, "STATE_DIR", os.path.join(self.tmp, "state"))
        self.state_patch.start()
        self.registry_path = os.path.join(self.tmp, "hooks.toml")
        Path(self.registry_path).write_text(
            textwrap.dedent(
                """
                [hooks.repeat-deny-stop]
                mode = "stop"
                why_mode = "habit"
                summary = "Test registry entry."

                [thresholds]
                min_closed_findings = 30
                promote_max_ignore_rate = 0.02
                demote_min_ignore_rate = 0.10
                review_min_ignore_rate = 0.50
                review_min_unchecked_rate = 0.05
                followup_window_checks = 3
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.state_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mode_override_warns_when_registry_would_stop(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.tmp, "metrics-override"),
                "CATSTACK_HOOK_MODE_REPEAT_DENY_STOP": "warn",
            },
            clear=False,
        ):
            self.run_entry(self.batch("first"))
            code, out, err = self.run_entry(self.batch("second"))
            rows = self.rows("metrics-override")

        self.assertEqual(0, code)
        self.assertEqual("", err)
        body = json.loads(out)
        self.assertIn("Stop calling tools", body["hookSpecificOutput"]["additionalContext"])
        finding_rows = [row for row in rows if row["rule_id"] == "repeat-deny-stop.repeated-deny"]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": os.path.join(self.tmp, "metrics-events")},
            clear=False,
        ):
            os.environ.pop("CATSTACK_HOOK_MODE_REPEAT_DENY_STOP", None)
            self.run_entry(self.batch("first"))
            self.run_entry(self.batch("second"))
            rows = self.rows("metrics-events")

        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("repeat-deny-stop.repeated-deny", finding_rows[0]["rule_id"])
        self.assertEqual("stopped", finding_rows[0]["action"])

    def batch(self, tool_id: str) -> dict[str, object]:
        return {
            "session_id": "sdk-mode-session",
            "hook_event_name": "PostToolBatch",
            "registry_path": self.registry_path,
            "tool_calls": [
                {
                    "tool_name": "Bash",
                    "tool_input": {},
                    "tool_use_id": tool_id,
                    "tool_response": REASON,
                }
            ],
        }

    def run_entry(self, payload: dict[str, object]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stdio(out, err):
            try:
                claude_post_tool_batch.main()
            except SystemExit as exc:
                return int(exc.code or 0), out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()

    def rows(self, metrics_subdir: str) -> list[dict[str, object]]:
        files = list((Path(self.tmp) / metrics_subdir).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


@contextlib.contextmanager
def redirect_stdio(stdout: io.StringIO, stderr: io.StringIO):
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
