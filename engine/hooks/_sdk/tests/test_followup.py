from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import events
import runtime
from finding import Finding


HOOK = "demo-followup"
OVERRIDE_ENV = "CATSTACK_HOOK_MODE_DEMO_FOLLOWUP"


class FollowupTest(unittest.TestCase):
    def test_refire_on_same_subject_closes_older_finding_as_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            registry_path = self._registry(tmp, mode="warn", window=3)
            event = self._event(registry_path, "session-ignore")
            env = self._env(metrics, "")

            self._run(event, env, [self._finding("subject-a")])
            first = self._finding_rows(metrics)[0]
            self._run(event, env, [self._finding("subject-a")])
            followups = self._followup_rows(metrics)

        self.assertEqual(1, len(followups))
        self.assertEqual("ignored", followups[0]["outcome"])
        self.assertEqual(first["finding_id"], followups[0]["finding_id"])
        self.assertEqual(first["subject_hash"], followups[0]["subject_hash"])

    def test_no_refire_within_window_closes_finding_as_acted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            registry_path = self._registry(tmp, mode="warn", window=3)
            event = self._event(registry_path, "session-acted")
            env = self._env(metrics, "")

            self._run(event, env, [self._finding("subject-b")])
            first = self._finding_rows(metrics)[0]
            self._run(event, env, [])
            self._run(event, env, [])
            self._run(event, env, [])
            followups = self._followup_rows(metrics)

        self.assertEqual(1, len(followups))
        self.assertEqual("acted", followups[0]["outcome"])
        self.assertEqual(first["finding_id"], followups[0]["finding_id"])

    def test_session_end_closes_remaining_finding_as_acted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            registry_path = self._registry(tmp, mode="warn", window=3)
            env = self._env(metrics, "")

            self._run(self._event(registry_path, "session-end"), env, [self._finding("subject-end")])
            first = self._finding_rows(metrics)[0]
            stop_event = self._event(registry_path, "session-end")
            stop_event["hook_event_name"] = "Stop"
            self._run(stop_event, env, [])
            followups = self._followup_rows(metrics)

        self.assertEqual(1, len(followups))
        self.assertEqual("acted", followups[0]["outcome"])
        self.assertEqual(first["finding_id"], followups[0]["finding_id"])

    def test_lower_override_mode_on_same_subject_closes_finding_as_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            registry_path = self._registry(tmp, mode="stop", window=3)
            event = self._event(registry_path, "session-override")

            self._run(event, self._env(metrics, ""), [self._finding("subject-c")])
            first = self._finding_rows(metrics)[0]
            self._run(event, self._env(metrics, "warn"), [self._finding("subject-c")])
            followups = self._followup_rows(metrics)

        self.assertEqual(1, len(followups))
        self.assertEqual("overridden", followups[0]["outcome"])
        self.assertEqual(first["finding_id"], followups[0]["finding_id"])

    def test_unreadable_state_file_writes_unchecked_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics"
            registry_path = self._registry(tmp, mode="warn", window=3)
            session_id = "session-unchecked"
            state_dir = metrics / "followup"
            state_dir.mkdir(parents=True)
            (state_dir / f"{session_id}.json").write_text("{not json", encoding="utf-8")

            self._run(
                self._event(registry_path, session_id),
                self._env(metrics, ""),
                [self._finding("subject-d")],
            )
            followups = self._followup_rows(metrics)

        self.assertEqual(1, len(followups))
        self.assertEqual("unchecked", followups[0]["outcome"])
        self.assertEqual("followup", followups[0]["action"])

    def test_prune_old_event_files_runs_at_most_once_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            old = self._event_file(tmp, 31)
            fresh = self._event_file(tmp, 1)
            events.prune_old_event_files(days=30)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

            second_old = self._event_file(tmp, 32)
            events.prune_old_event_files(days=30)
            self.assertTrue(second_old.exists())

    def test_prune_failure_prints_hook_error_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_METRICS_DIR": tmp}, clear=False
        ):
            self._event_file(tmp, 31)
            err = io.StringIO()
            with mock.patch.object(Path, "unlink", side_effect=OSError("nope")):
                events.prune_old_event_files(days=30, stderr=err)

        self.assertRegex(err.getvalue(), r"^catstack-hook-error metrics: event prune failed:")

    def _run(
        self,
        event: dict[str, object],
        env: dict[str, str],
        findings: list[Finding],
    ) -> None:
        with mock.patch.dict(os.environ, env, clear=False), self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook(HOOK, "codex", lambda _event: findings)
        self.assertEqual(0, caught.exception.code)

    def _finding(self, subject: str) -> Finding:
        return Finding("demo.rule", subject, "Demo message", "demo evidence")

    def _event(self, registry_path: Path, session_id: str) -> dict[str, object]:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "registry_path": str(registry_path),
        }

    def _env(self, metrics: Path, override: str) -> dict[str, str]:
        return {"CATSTACK_HOOK_METRICS_DIR": str(metrics), OVERRIDE_ENV: override}

    def _registry(self, directory: str, mode: str, window: int) -> Path:
        path = Path(directory) / "hooks.toml"
        path.write_text(
            f"""
[hooks.{HOOK}]
mode = "{mode}"
why_mode = "attention"
summary = "Demo followup hook."

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = {window}
""".lstrip(),
            encoding="utf-8",
        )
        return path

    def _event_file(self, directory: str, age_days: int) -> Path:
        file_date = datetime.now(timezone.utc).date() - timedelta(days=age_days)
        path = Path(directory) / f"events-{file_date.isoformat()}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        return path

    def _rows(self, metrics: Path) -> list[dict[str, object]]:
        rows = []
        for path in sorted(metrics.glob("events-*.jsonl")):
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return rows

    def _finding_rows(self, metrics: Path) -> list[dict[str, object]]:
        return [row for row in self._rows(metrics) if row["action"] in {"warned", "stopped"}]

    def _followup_rows(self, metrics: Path) -> list[dict[str, object]]:
        return [row for row in self._rows(metrics) if row["action"] == "followup"]

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


if __name__ == "__main__":
    unittest.main()
