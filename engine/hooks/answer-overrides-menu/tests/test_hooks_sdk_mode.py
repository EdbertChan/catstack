#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


HOOK_DIR = Path(__file__).resolve().parents[1]
FIXTURE = HOOK_DIR / "tests" / "fixtures" / "real_free_text_override.json"
sys.path.insert(0, str(HOOK_DIR))

import claude_posttooluse  # noqa: E402


def load_firing_payload(session_id: str) -> dict[str, object]:
    with FIXTURE.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["session_id"] = session_id
    return payload


def run_claude(payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_posttooluse.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


@contextmanager
def hook_env(**updates: str):
    old = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CATSTACK_HOOK_METRICS_DIR"] = tmp
        os.environ.update(updates)
        try:
            yield Path(tmp)
        finally:
            os.environ.clear()
            os.environ.update(old)


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class AnswerOverridesMenuSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        with hook_env(CATSTACK_HOOK_MODE_ANSWER_OVERRIDES_MENU="stop"):
            stop_code, stop_out, stop_err = run_claude(load_firing_payload("answer-menu-stop"))
        with hook_env(CATSTACK_HOOK_MODE_ANSWER_OVERRIDES_MENU="warn"):
            warn_code, warn_out, warn_err = run_claude(load_firing_payload("answer-menu-warn"))

        self.assertEqual(0, stop_code)
        self.assertEqual("", stop_err)
        stop_body = json.loads(stop_out)
        self.assertEqual("PostToolUse", stop_body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("answer-overrides-menu", stop_body["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertNotIn("decision", warning)
        self.assertIn(
            "answer-overrides-menu",
            warning["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = load_firing_payload("answer-menu-events")
        payload["tool_response"]["response"] = "use the user's typed parameters"
        with hook_env(CATSTACK_HOOK_MODE_ANSWER_OVERRIDES_MENU="warn") as tmp:
            code, out, err = run_claude(payload)
            rows = event_rows(tmp)

        finding_rows = [row for row in rows if row["action"] == "warned"]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("answer-overrides-menu", out)
        self.assertEqual(3, len(finding_rows))
        self.assertEqual(
            [
                "answer-overrides-menu.unlisted-answer",
                "answer-overrides-menu.unlisted-answer",
                "answer-overrides-menu.freeform-response",
            ],
            [row["rule_id"] for row in finding_rows],
        )
        self.assertTrue(all(row["hook"] == "answer-overrides-menu" for row in finding_rows))
        self.assertTrue(all(row["mode"] == "warn" for row in finding_rows))
        self.assertTrue(all(row["mode_source"] == "override" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
