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

HOOKS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HOOKS_DIR.parents[1]
FIXTURES = REPO_ROOT / "skills" / "reflect" / "scripts" / "tests" / "fixtures"
sys.path.insert(0, str(HOOKS_DIR))

import claude_stop_reflect  # noqa: E402
import detect  # noqa: E402

sys.path.insert(0, str(HOOKS_DIR.parent / "_flags"))
import flags  # noqa: E402


class ReflectOnThrashSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.metrics = Path(self.tmp.name) / "metrics"
        self.state = Path(self.tmp.name) / "state"
        self.transcript = str(FIXTURES / "token_thrash_session.jsonl")
        detect.STATE_DIR = str(self.state)

    def test_warn_override_turns_today_stop_into_warning(self) -> None:
        registry = self._registry("stop")
        payload = {
            "hook_event_name": "Stop",
            "registry_path": str(registry),
            "session_id": "mode-session",
            "transcript_path": self.transcript,
        }
        with patch.dict(os.environ, self._env({"CATSTACK_HOOK_MODE_REFLECT_ON_THRASH": "warn"}), clear=False):
            code, stdout, stderr = self._run_claude(payload)

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        self.assertIn("automate-me", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "event-session",
            "transcript_path": self.transcript,
        }
        with patch.dict(os.environ, self._env({"CATSTACK_HOOK_MODE_REFLECT_ON_THRASH": "stop"}), clear=False):
            code, _stdout, stderr = self._run_claude(payload)
            rows = self._event_rows()

        self.assertEqual(2, code)
        self.assertIn("automate-me", stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual("reflect-on-thrash.intervention-must-automate", rows[0]["rule_id"])
        self.assertEqual("reflect-on-thrash", rows[0]["hook"])
        self.assertEqual("stopped", rows[0]["action"])

    def _env(self, extra: dict[str, str]) -> dict[str, str]:
        env = {
            flags.REFLECT_ENFORCEMENT: "1",
            "CATSTACK_HOOK_METRICS_DIR": str(self.metrics),
            "REFLECT_ON_THRASH_STATE_DIR": str(self.state),
        }
        env.update(extra)
        return env

    def _run_claude(self, payload: dict[str, object]) -> tuple[int, str, str]:
        with self._stdio(json.dumps(payload)):
            try:
                claude_stop_reflect.main()
            except SystemExit as exc:
                code = int(exc.code or 0)
            else:
                code = 0
            return code, sys.stdout.getvalue(), sys.stderr.getvalue()

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

    def _event_rows(self) -> list[dict[str, object]]:
        files = list(self.metrics.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    def _registry(self, mode: str) -> Path:
        path = Path(self.tmp.name) / "hooks.toml"
        path.write_text(
            "\n".join(
                [
                    "[hooks.reflect-on-thrash]",
                    f'mode = "{mode}"',
                    'why_mode = "habit"',
                    'summary = "Suggests a reflect pass when a session goes in circles."',
                    "",
                    "[thresholds]",
                    "min_closed_findings = 30",
                    "promote_max_ignore_rate = 0.02",
                    "demote_min_ignore_rate = 0.10",
                    "review_min_ignore_rate = 0.50",
                    "review_min_unchecked_rate = 0.05",
                    "followup_window_checks = 3",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
