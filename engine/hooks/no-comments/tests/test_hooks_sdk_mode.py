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

import claude_pretooluse  # noqa: E402


COMMENT_EDIT = {
    "hook_event_name": "PreToolUse",
    "session_id": "session-no-comments",
    "tool_name": "Edit",
    "tool_input": {
        "file_path": "/repo/hook.py",
        "old_string": "x",
        "new_string": "value = 1\n# explain why\n",
    },
}


class NoCommentsSdkModeTest(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "CATSTACK_HOOK_MODE_NO_COMMENTS": "warn",
                "CATSTACK_HOOK_METRICS_DIR": tmp,
            },
            clear=False,
        ), self._stdio(json.dumps(COMMENT_EDIT)):
            claude_pretooluse.main()
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()

        self.assertEqual("", stderr)
        body = json.loads(stdout)
        self.assertIn(
            "no-comments: this edit adds 1 comment line(s)",
            body["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": tmp},
            clear=False,
        ), self._stdio(json.dumps(COMMENT_EDIT)):
            with self.assertRaises(SystemExit) as caught:
                claude_pretooluse.main()
            rows = self._rows(tmp)

        self.assertEqual(2, caught.exception.code)
        finding_rows = [row for row in rows if row["action"] == "stopped"]
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("no-comments.added-comment", finding_rows[0]["rule_id"])
        self.assertEqual("no-comments", finding_rows[0]["hook"])

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
