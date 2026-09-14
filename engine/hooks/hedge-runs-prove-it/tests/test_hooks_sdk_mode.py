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

HOOK_DIR = Path(__file__).resolve().parents[1]
FIXTURES = HOOK_DIR / "tests" / "fixtures"
sys.path.insert(0, str(HOOK_DIR))

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def transcript_file() -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write(json.dumps({
        "type": "user",
        "message": {"role": "user", "content": "what is this file?"},
    }) + "\n")
    tmp.close()
    return tmp.name


class SdkModeTest(unittest.TestCase):
    def test_warn_override_changes_claude_stop_to_additional_context(self) -> None:
        case = load("hedges_fires.json")[0]
        path = transcript_file()
        try:
            payload = {
                "hook_event_name": "Stop",
                "session_id": "hedge-warn-override",
                "last_assistant_message": case["reply"],
                "transcript_path": path,
            }
            with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ,
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_HEDGE_RUNS_PROVE_IT": "warn",
                },
                clear=False,
            ), self._stdio(json.dumps(payload)):
                code = self._main_exit_code()
                stdout = sys.stdout.getvalue()
                stderr = sys.stderr.getvalue()
                rows = self._rows(tmp)
        finally:
            os.unlink(path)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("presumably", output["additionalContext"])
        self.assertEqual(1, len(rows))
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("override", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        case = load("hedges_fires.json")[0]
        path = transcript_file()
        try:
            payload = {
                "hook_event_name": "Stop",
                "session_id": "hedge-event-rows",
                "last_assistant_message": case["reply"],
                "transcript_path": path,
            }
            findings = detect.detect(payload)
            with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ,
                {
                    "CATSTACK_HOOK_METRICS_DIR": tmp,
                    "CATSTACK_HOOK_MODE_HEDGE_RUNS_PROVE_IT": "stop",
                },
                clear=False,
            ), self._stdio(json.dumps(payload)):
                code = self._main_exit_code()
                rows = self._rows(tmp)
        finally:
            os.unlink(path)

        self.assertEqual(2, code)
        self.assertEqual(1, len(findings))
        self.assertEqual(len(findings), len(rows))
        self.assertEqual(detect.RULE_HEDGE, findings[0].rule_id)
        self.assertEqual(detect.RULE_HEDGE, rows[0]["rule_id"])
        self.assertEqual("hedge-runs-prove-it", rows[0]["hook"])
        self.assertEqual("stopped", rows[0]["action"])

    def _main_exit_code(self) -> int:
        try:
            claude_stop_check.main()
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0

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
