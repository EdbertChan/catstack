#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import judge  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402


RULE_HIT = "wrong-check-reflect.claim-retracted"
RULE_UNCHECKED = "wrong-check-reflect.unchecked"


def run_claude(payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


class HooksSdkModeTest(JudgeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.registry_tmp = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.registry_tmp.name) / "hooks.toml"
        self.registry_path.write_text(
            """
[hooks.wrong-check-reflect]
mode = "stop"
why_mode = "habit"
summary = "Suggests reflect after a claim is taken back."

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
""".lstrip(),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.registry_tmp.cleanup()
        super().tearDown()

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stopped_transcript = self._transcript("stopped.jsonl")
        self._write_verdict(stopped_transcript, "hit-stop", "hit", detect.FOLLOWUP, RULE_HIT)
        stop_code, stop_out, stop_err = run_claude({
            "hook_event_name": "Stop",
            "session_id": "sdk-stop",
            "transcript_path": stopped_transcript,
            "stop_hook_active": True,
            "registry_path": str(self.registry_path),
        })

        warned_transcript = self._transcript("warned.jsonl")
        self._write_verdict(warned_transcript, "hit-warn", "hit", detect.FOLLOWUP, RULE_HIT)
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_WRONG_CHECK_REFLECT": "warn"}, clear=False):
            warn_code, warn_out, warn_err = run_claude({
                "hook_event_name": "Stop",
                "session_id": "sdk-warn",
                "transcript_path": warned_transcript,
                "stop_hook_active": True,
                "registry_path": str(self.registry_path),
            })

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn(detect.FOLLOWUP, stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertIn(
            detect.FOLLOWUP,
            warning["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        transcript = self._transcript("events.jsonl")
        self._write_verdict(transcript, "hit-one", "hit", detect.FOLLOWUP, RULE_HIT)
        self._write_verdict(transcript, "unchecked-one", "unchecked", "could not judge", RULE_UNCHECKED)

        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_WRONG_CHECK_REFLECT": "warn"}, clear=False):
            code, out, err = run_claude({
                "hook_event_name": "Stop",
                "session_id": "sdk-events",
                "transcript_path": transcript,
                "stop_hook_active": True,
                "registry_path": str(self.registry_path),
            })

        today = datetime.now(timezone.utc).date().isoformat()
        event_file = Path(self.state.name) / "metrics" / f"events-{today}.jsonl"
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row.get("rule_id") in {RULE_HIT, RULE_UNCHECKED}]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn(detect.FOLLOWUP, out)
        self.assertEqual([RULE_HIT, RULE_UNCHECKED], [row["rule_id"] for row in finding_rows])
        self.assertEqual(["warned", "warned"], [row["action"] for row in finding_rows])
        self.assertEqual(["override", "override"], [row["mode_source"] for row in finding_rows])

    def _transcript(self, name: str) -> str:
        path = Path(self.state.name) / name
        path.write_text("", encoding="utf-8")
        return str(path)

    def _write_verdict(
        self,
        transcript: str,
        verdict_id: str,
        outcome: str,
        on_hit: str,
        rule_id: str,
    ) -> None:
        folder = Path(judge.verdict_dir(transcript))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{verdict_id}.json").write_text(
            json.dumps({
                "id": verdict_id,
                "hook": "wrong-check-reflect",
                "transcript": transcript,
                "outcome": outcome,
                "on_hit": on_hit,
                "reason": outcome,
                "rule_id": rule_id,
            }),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
