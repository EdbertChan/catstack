from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]


class EntrypointHooks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.metrics = Path(self.tmp.name) / "metrics"
        self.metrics.mkdir(parents=True)
        self.log = self.metrics / "runs.jsonl"

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home), "CATSTACK_HOOK_METRICS_DIR": str(self.metrics)}

    def row(self, harness: str = "claude", hook: str = "demo") -> dict[str, object]:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "harness": harness,
            "hook": hook,
            "script": "x.py",
            "event": "UserPromptSubmit",
            "session_id": "s1",
            "outcome": "crashed",
            "exit_code": 1,
            "duration_ms": 4,
            "stdout_bytes": 0,
            "stderr_tail": "boom\nmore",
        }

    def write_rows(self, rows: list[dict[str, object]]) -> None:
        with self.log.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def run_hook(self, script: str, payload: dict[str, object] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HOOK_DIR / script)],
            input=json.dumps(payload or {"session_id": "s1"}),
            capture_output=True,
            text=True,
            env=self.env(),
            timeout=10,
        )

    def assert_clean_run(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def wait_for_scan(self, session: str = "s1") -> None:
        deadline = time.monotonic() + 10
        while list(self.metrics.glob(f"hook-health-*-{session}.scanning")) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(list(self.metrics.glob(f"hook-health-*-{session}.scanning")), [], "background scan did not finish within 10s")

    def assert_notice_once(self, script: str, harness: str, expected_shape: str) -> None:
        self.assert_clean_run(self.run_hook(script))
        self.write_rows([self.row(harness)])
        self.assert_clean_run(self.run_hook(script))
        self.wait_for_scan()
        shown = self.run_hook(script)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(shown.stderr, "")
        self.assertIn("hook-health: 1 hook run(s) failed", shown.stdout)
        self.assertIn(expected_shape, json.dumps(json.loads(shown.stdout)))
        self.wait_for_scan()
        self.assert_clean_run(self.run_hook(script))

    def test_claude_positive_notice_once(self) -> None:
        self.assert_notice_once("claude_prompt_submit.py", "claude", "hookSpecificOutput")

    def test_cursor_positive_notice_once(self) -> None:
        self.assert_notice_once("cursor_before_submit.py", "cursor", "additional_context")

    def test_codex_positive_notice_once(self) -> None:
        self.assert_notice_once("codex_prompt_submit.py", "codex", "hookSpecificOutput")

    def test_new_session_skips_failures_already_in_the_log(self) -> None:
        self.write_rows([self.row("claude")])
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.wait_for_scan()
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))

    def test_prompt_does_not_wait_for_the_scan(self) -> None:
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.write_rows([self.row("claude")] * 200_000)
        started = time.monotonic()
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        elapsed = time.monotonic() - started
        self.wait_for_scan()
        self.assertLess(elapsed, 0.5 * self.scan_seconds(), f"prompt took {elapsed:.2f}s")

    def scan_seconds(self) -> float:
        started = time.monotonic()
        with self.log.open(encoding="utf-8") as handle:
            for line in handle:
                json.loads(line)
        return time.monotonic() - started

    def test_missing_log_prints_nothing_and_exits_zero(self) -> None:
        result = self.run_hook("claude_prompt_submit.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unreadable_log_emits_notice_and_exits_zero(self) -> None:
        self.log.mkdir()
        for script in ("claude_prompt_submit.py", "cursor_before_submit.py", "codex_prompt_submit.py"):
            payload = {"session_id": f"s-{script}"}
            for _ in range(2):
                self.assert_clean_run(self.run_hook(script, payload))
                self.wait_for_scan(f"s-{script}")
            result = self.run_hook(script, payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("hook failures are unchecked this turn", result.stdout)

    def test_malformed_payload_logs_caught_error_and_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK_DIR / "claude_prompt_submit.py")],
            input="not-json",
            capture_output=True,
            text=True,
            env=self.env(),
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("catstack-hook-error hook-health: JSONDecodeError", result.stderr)


if __name__ == "__main__":
    unittest.main()
