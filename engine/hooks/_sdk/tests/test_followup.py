from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import events  # noqa: E402
import followup  # noqa: E402
from finding import Finding  # noqa: E402


@contextmanager
def temp_metrics_dir():
    old_dir = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CATSTACK_HOOK_METRICS_DIR"] = tmp
        try:
            yield Path(tmp)
        finally:
            if old_dir is None:
                os.environ.pop("CATSTACK_HOOK_METRICS_DIR", None)
            else:
                os.environ["CATSTACK_HOOK_METRICS_DIR"] = old_dir


def finding(rule_id: str = "demo.rule", subject: str = "subject-a") -> Finding:
    return Finding(rule_id, subject, "Message", "Evidence")


def append_and_update(
    *,
    event: dict[str, object],
    hook: str = "diu-stop",
    mode: str = "stop",
    mode_source: str = "registry",
    findings: list[Finding] | None = None,
    window: int = 3,
) -> list[dict[str, object]]:
    rows = events.append_events(
        event=event,
        harness="codex",
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        findings=[] if findings is None else findings,
        duration_ms=1,
    )
    followup.update_followups(
        event=event,
        harness="codex",
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        rows=rows,
        followup_window_checks=window,
    )
    return rows


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class FollowupTest(unittest.TestCase):
    def test_refire_on_same_subject_within_window_closes_older_finding_as_ignored(self) -> None:
        with temp_metrics_dir() as tmp:
            first = append_and_update(event={"session_id": "s-ignored"}, findings=[finding()])
            append_and_update(event={"session_id": "s-ignored"}, findings=[finding()])

            followups = [row for row in event_rows(tmp) if row["action"] == "followup"]

        self.assertEqual(1, len(followups))
        self.assertEqual("ignored", followups[0]["outcome"])
        self.assertEqual(first[0]["finding_id"], followups[0]["finding_id"])

    def test_no_refire_within_window_closes_finding_as_acted(self) -> None:
        with temp_metrics_dir() as tmp:
            first = append_and_update(event={"session_id": "s-acted"}, findings=[finding()])
            append_and_update(event={"session_id": "s-acted"}, findings=[])
            append_and_update(event={"session_id": "s-acted"}, findings=[])
            append_and_update(event={"session_id": "s-acted"}, findings=[])

            followups = [row for row in event_rows(tmp) if row["action"] == "followup"]

        self.assertEqual(1, len(followups))
        self.assertEqual("acted", followups[0]["outcome"])
        self.assertEqual(first[0]["finding_id"], followups[0]["finding_id"])

    def test_lower_override_mode_on_same_subject_closes_finding_as_overridden(self) -> None:
        with temp_metrics_dir() as tmp:
            first = append_and_update(event={"session_id": "s-overridden"}, findings=[finding()])
            append_and_update(
                event={"session_id": "s-overridden"},
                mode="warn",
                mode_source="override",
                findings=[finding()],
            )

            followups = [row for row in event_rows(tmp) if row["action"] == "followup"]

        self.assertEqual(1, len(followups))
        self.assertEqual("overridden", followups[0]["outcome"])
        self.assertEqual(first[0]["finding_id"], followups[0]["finding_id"])

    def test_session_end_closes_open_findings_as_acted(self) -> None:
        with temp_metrics_dir() as tmp:
            first = append_and_update(event={"session_id": "s-ended"}, findings=[finding()])
            append_and_update(event={"session_id": "s-ended", "hook_event_name": "sessionEnd"}, findings=[])

            followups = [row for row in event_rows(tmp) if row["action"] == "followup"]

        self.assertEqual(1, len(followups))
        self.assertEqual("acted", followups[0]["outcome"])
        self.assertEqual(first[0]["finding_id"], followups[0]["finding_id"])

    def test_unreadable_state_writes_unchecked_followup_without_guessing(self) -> None:
        err = StringIO()
        with temp_metrics_dir() as tmp:
            state_path = followup._state_path("s-corrupt")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{not json", encoding="utf-8")

            rows = events.append_events(
                event={"session_id": "s-corrupt"},
                harness="codex",
                hook="diu-stop",
                mode="stop",
                mode_source="registry",
                findings=[finding()],
                duration_ms=1,
            )
            with redirect_stderr(err):
                followup.update_followups(
                    event={"session_id": "s-corrupt"},
                    harness="codex",
                    hook="diu-stop",
                    mode="stop",
                    mode_source="registry",
                    rows=rows,
                    followup_window_checks=3,
                )

            followups = [row for row in event_rows(tmp) if row["action"] == "followup"]

        self.assertEqual(1, len(followups))
        self.assertEqual("unchecked", followups[0]["outcome"])
        self.assertTrue(err.getvalue().startswith("catstack-hook-error followup"))

    def test_prune_old_event_files_runs_at_most_once_per_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        with temp_metrics_dir() as tmp:
            old = tmp / f"events-{(today - timedelta(days=31)).isoformat()}.jsonl"
            recent = tmp / f"events-{(today - timedelta(days=30)).isoformat()}.jsonl"
            second_old = tmp / f"events-{(today - timedelta(days=32)).isoformat()}.jsonl"
            old.write_text("{}\n", encoding="utf-8")
            recent.write_text("{}\n", encoding="utf-8")

            events.prune_old_event_files(days=30)
            second_old.write_text("{}\n", encoding="utf-8")
            events.prune_old_event_files(days=30)

            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(second_old.exists())

    def test_prune_failure_prints_catstack_hook_error_line(self) -> None:
        today = datetime.now(timezone.utc).date()
        err = StringIO()
        with temp_metrics_dir() as tmp:
            old = tmp / f"events-{(today - timedelta(days=31)).isoformat()}.jsonl"
            old.write_text("{}\n", encoding="utf-8")

            with patch.object(Path, "unlink", side_effect=OSError("nope")):
                with redirect_stderr(err):
                    events.prune_old_event_files(days=30)

        self.assertTrue(err.getvalue().startswith("catstack-hook-error events-prune"))


if __name__ == "__main__":
    unittest.main()
