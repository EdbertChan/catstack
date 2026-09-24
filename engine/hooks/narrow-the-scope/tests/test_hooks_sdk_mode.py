#!/usr/bin/env python3
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
SDK_DIR = HOOKS_DIR.parent / "_sdk"
sys.path.insert(0, str(HOOKS_DIR))
sys.path.insert(0, str(SDK_DIR))


class HooksSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for mod in ("state", "detect", "claude_posttooluse"):
            sys.modules.pop(mod, None)
        self.state_dir = Path(self.tmp.name) / "state"
        self.metrics_dir = Path(self.tmp.name) / "metrics"
        self.registry_path = Path(self.tmp.name) / "hooks.toml"
        self.registry_path.write_text(
            """
[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3

[hooks.narrow-the-scope]
mode = "stop"
why_mode = "attention"
summary = "test registry override"
""".lstrip(),
            encoding="utf-8",
        )

    def test_warn_override_changes_stop_registry_response_to_warning(self) -> None:
        event = self._event("override-session")
        with mock.patch.dict(
            os.environ,
            {
                "CATSTACK_NARROW_THE_SCOPE_STATE_DIR": str(self.state_dir),
                "CATSTACK_HOOK_METRICS_DIR": str(self.metrics_dir),
                "CATSTACK_HOOK_MODE_NARROW_THE_SCOPE": "warn",
            },
            clear=False,
        ):
            self._run(event)
            self._run(event)
            code, stdout, stderr = self._run(event)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        self.assertEqual("PostToolUse", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("narrow-the-scope: 3 edits", body["hookSpecificOutput"]["additionalContext"])
        row = self._finding_rows()[0]
        self.assertEqual("warn", row["mode"])
        self.assertEqual("override", row["mode_source"])
        self.assertEqual("warned", row["action"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        event = self._event("event-session")
        with mock.patch.dict(
            os.environ,
            {
                "CATSTACK_NARROW_THE_SCOPE_STATE_DIR": str(self.state_dir),
                "CATSTACK_HOOK_METRICS_DIR": str(self.metrics_dir),
            },
            clear=False,
        ):
            self._run(event)
            self._run(event)
            self._run(event)

        rows = self._finding_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual("narrow-the-scope.edit-streak", rows[0]["rule_id"])
        self.assertEqual("narrow-the-scope", rows[0]["hook"])

    def _event(self, session_id: str) -> dict[str, object]:
        return {
            "hook_event_name": "PostToolUse",
            "session_id": session_id,
            "registry_path": str(self.registry_path),
            "tool_name": "Edit",
            "tool_input": {"file_path": "/x/a.py"},
        }

    def _run(self, event: dict[str, object]) -> tuple[int, str, str]:
        import claude_posttooluse

        with self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                claude_posttooluse.main()
            return int(caught.exception.code or 0), sys.stdout.getvalue(), sys.stderr.getvalue()

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

    def _finding_rows(self) -> list[dict[str, object]]:
        files = list(self.metrics_dir.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [
            row
            for row in (json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines())
            if row["rule_id"]
        ]


if __name__ == "__main__":
    unittest.main()
