from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import claude_pretooluse  # noqa: E402


AGENT_A = {"session_id": "sdk-mode-session", "transcript_path": "/x/agent-aaaa1111.jsonl"}
AGENT_B = {"session_id": "sdk-mode-session", "transcript_path": "/x/agent-bbbb2222.jsonl"}
RULE_ID = "scratchpad-collision.cross-agent-write"


class SdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.scratchpad = Path(self.tmp.name) / "scratchpad"
        self.scratchpad.mkdir()
        self.body = self.scratchpad / "pr-body.md"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_mode_override_warns_when_registry_would_stop(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CLAUDE_SCRATCHPAD": str(self.scratchpad),
                "CATSTACK_HOOK_METRICS_DIR": str(Path(self.tmp.name) / "metrics-override"),
                "CATSTACK_HOOK_MODE_SCRATCHPAD_COLLISION": "warn",
            },
            clear=False,
        ):
            self.run_entry(AGENT_A)
            self.body.write_text("PR #7 body", encoding="utf-8")
            code, out, err = self.run_entry(AGENT_B)

        self.assertEqual(0, code)
        self.assertEqual("", err)
        warning = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("another agent wrote pr-body.md", warning)
        rows = self.rows("metrics-override")
        finding_rows = [row for row in rows if row["rule_id"] == RULE_ID]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CLAUDE_SCRATCHPAD": str(self.scratchpad),
                "CATSTACK_HOOK_METRICS_DIR": str(Path(self.tmp.name) / "metrics-events"),
            },
            clear=False,
        ):
            os.environ.pop("CATSTACK_HOOK_MODE_SCRATCHPAD_COLLISION", None)
            self.run_entry(AGENT_A)
            self.body.write_text("PR #7 body", encoding="utf-8")
            code, _out, _err = self.run_entry(AGENT_B)
            rows = self.rows("metrics-events")

        self.assertEqual(2, code)
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual(RULE_ID, finding_rows[0]["rule_id"])
        self.assertEqual("stopped", finding_rows[0]["action"])

    def run_entry(self, agent: dict[str, str]) -> tuple[int, str, str]:
        payload = {**agent, "tool_name": "Write", "tool_input": {"file_path": str(self.body)}}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stdio(out, err):
            try:
                claude_pretooluse.main()
            except SystemExit as exc:
                return int(exc.code or 0), out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()

    def rows(self, metrics_subdir: str) -> list[dict[str, object]]:
        files = list((Path(self.tmp.name) / metrics_subdir).glob("events-*.jsonl"))
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
