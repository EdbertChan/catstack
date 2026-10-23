from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
RUNNER_DIR = HOOK_DIR.parent / "_runner"
sys.path.insert(0, str(HOOK_DIR))

import detect  # noqa: E402

UNCHECKED_ROW = {
    "hook": "technical-writing-guard",
    "script": "claude_stop_check.py",
    "outcome": "blocked",
    "exit_code": 2,
    "rule_ids": ["technical-writing-guard.unchecked"],
    "stderr_tail": "The document check could not load. Leave the reply unchecked.\n",
    "harness": "claude",
    "event": "Stop",
}
HARNESS_SCRIPTS = {
    "claude": "claude_prompt_submit.py",
    "cursor": "cursor_before_submit.py",
    "codex": "codex_prompt_submit.py",
}


SILENT_STDOUT = ("", '{"continue": true}\n')

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
        self.assertIn(result.stdout, SILENT_STDOUT)
        self.assertEqual(result.stderr, "")

    def wait_for_scan(self, session: str = "s1") -> None:
        deadline = time.monotonic() + 120
        while list(self.metrics.glob(f"hook-health-*-{session}.scanning")) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(list(self.metrics.glob(f"hook-health-*-{session}.scanning")), [], "background scan did not finish within 120s")

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

    def crash_through_runner(self, harness: str, message: str = "boom") -> None:
        root = self.home / f".{harness}" / "hooks"
        (root / "_runner").mkdir(parents=True, exist_ok=True)
        (root / "fixture").mkdir(parents=True, exist_ok=True)
        for name in ("run.py", "outcome.py"):
            shutil.copy2(RUNNER_DIR / name, root / "_runner" / name)
        (root / "fixture" / "crash.py").write_text(f"raise RuntimeError({message!r})\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(root / "_runner" / "run.py"), "fixture/crash.py"],
            input=json.dumps({"hook_event_name": "Stop", "session_id": "s1"}),
            capture_output=True,
            text=True,
            env=self.env(),
            timeout=10,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn(result.stdout, SILENT_STDOUT)

    def next_turn(self, script: str) -> subprocess.CompletedProcess[str]:
        self.assert_clean_run(self.run_hook(script))
        self.wait_for_scan()
        result = self.run_hook(script)
        self.wait_for_scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result

    def test_runner_crash_fires_one_notice_then_repeat_crash_does_not_notify(self) -> None:
        for harness, script in HARNESS_SCRIPTS.items():
            with self.subTest(harness=harness):
                self.assert_clean_run(self.run_hook(script))
                self.crash_through_runner(harness)
                self.crash_through_runner(harness)
                shown = self.next_turn(script)
                self.assertIn("hook-health: 2 hook run(s) failed", shown.stdout)
                self.assertEqual(shown.stdout.count("fixture/crash.py crashed"), 1, shown.stdout)
                self.assertIn("RuntimeError: boom", shown.stdout)
                self.crash_through_runner(harness)
                self.assertIn(self.next_turn(script).stdout, SILENT_STDOUT)

    def test_different_crash_in_same_session_still_fires(self) -> None:
        script = HARNESS_SCRIPTS["claude"]
        self.assert_clean_run(self.run_hook(script))
        self.crash_through_runner("claude")
        self.assertIn("RuntimeError: boom", self.next_turn(script).stdout)
        self.crash_through_runner("claude", "other")
        self.assertIn("RuntimeError: other", self.next_turn(script).stdout)

    def test_truncated_traceback_fires_notice_naming_the_exception(self) -> None:
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        row = self.row("claude")
        row["stderr_tail"] = 'ine 9, in f\n  File "/x.py", line 3, in <module>\n    g()\nKeyError: \'k\'\n'
        self.write_rows([row])
        shown = self.next_turn("claude_prompt_submit.py")
        self.assertIn("demo/x.py crashed (exit 1): KeyError: 'k'", shown.stdout)

    def test_new_session_skips_failures_already_in_the_log(self) -> None:
        self.write_rows([self.row("claude")])
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.wait_for_scan()
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))

    def test_rotated_log_is_read_from_the_start_of_the_new_file(self) -> None:
        self.write_rows([self.row("claude")] * 50)
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.wait_for_scan()
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.wait_for_scan()
        self.log.rename(self.metrics / "runs.jsonl.1")
        self.write_rows([self.row("claude")])
        self.assert_clean_run(self.run_hook("claude_prompt_submit.py"))
        self.wait_for_scan()
        shown = self.run_hook("claude_prompt_submit.py")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("hook-health: 1 hook run(s) failed", shown.stdout)

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
        self.assertIn(result.stdout, SILENT_STDOUT)

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
        self.assertIn(result.stdout, SILENT_STDOUT)
        self.assertIn("catstack-hook-error hook-health: JSONDecodeError", result.stderr)


class UncheckedOnEveryRun(unittest.TestCase):
    def test_hook_unchecked_on_every_run_is_reported(self) -> None:
        rows = [dict(UNCHECKED_ROW) for _ in range(3)]
        text = detect.notice(rows, "claude")
        self.assertIsNotNone(text)
        self.assertIn("technical-writing-guard reported unchecked on all 3 runs since the last prompt", text)
        self.assertIn("The document check could not load. Leave the reply unchecked.", text)
        self.assertIn("it is not checking anything", text)
        self.assertNotIn("blocked on purpose", text)

    def test_unchecked_rows_logged_as_action_are_reported(self) -> None:
        row = {**UNCHECKED_ROW, "outcome": "silent", "exit_code": 0, "rule_ids": [], "action": "unchecked"}
        text = detect.notice([dict(row) for _ in range(4)], "claude")
        self.assertIsNotNone(text)
        self.assertIn("reported unchecked on all 4 runs", text)

    def test_single_unchecked_run_stays_quiet(self) -> None:
        self.assertIsNone(detect.notice([dict(UNCHECKED_ROW)], "claude"))
        self.assertIsNone(detect.notice([dict(UNCHECKED_ROW) for _ in range(2)], "claude"))

    def test_hook_that_also_checked_something_stays_quiet(self) -> None:
        rows = [dict(UNCHECKED_ROW) for _ in range(3)]
        rows.append({**UNCHECKED_ROW, "rule_ids": ["technical-writing-guard.sentence"]})
        self.assertIsNone(detect.notice(rows, "claude"))

    def test_unchecked_notice_is_not_repeated_once_seen(self) -> None:
        rows = [dict(UNCHECKED_ROW) for _ in range(3)]
        seen = frozenset(detect.unchecked_signature(row) for row in rows)
        self.assertIsNone(detect.notice(rows, "claude", seen))


if __name__ == "__main__":
    unittest.main()
