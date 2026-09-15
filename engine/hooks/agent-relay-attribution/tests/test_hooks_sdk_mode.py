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
FIXTURES = HOOK_DIR / "tests" / "fixtures"
sys.path.insert(0, str(HOOK_DIR))

import claude_stop_check  # noqa: E402


def load(name: str) -> list[dict[str, object]]:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def transcript_file(lines: list[dict[str, object]]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def firing_payload(session_id: str = "agent-relay-sdk-test") -> dict[str, object]:
    entry = load("relay_fires.json")[0]
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "last_assistant_message": entry["reply"],
        "transcript_path": transcript_file(entry["transcript"]),
    }


def run_claude(payload: dict[str, object]) -> tuple[int | None, str, str]:
    stderr = StringIO()
    stdout = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, stderr.getvalue(), stdout.getvalue()
    return 0, stderr.getvalue(), stdout.getvalue()


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


class AgentRelaySdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_payload = firing_payload("agent-relay-mode-stop")
        warn_payload = firing_payload("agent-relay-mode-warn")
        try:
            with hook_env(CATSTACK_HOOK_MODE_AGENT_RELAY_ATTRIBUTION="stop"):
                stop_code, stop_err, stop_out = run_claude(stop_payload)
            with hook_env(CATSTACK_HOOK_MODE_AGENT_RELAY_ATTRIBUTION="warn"):
                warn_code, warn_err, warn_out = run_claude(warn_payload)
        finally:
            os.unlink(str(stop_payload["transcript_path"]))
            os.unlink(str(warn_payload["transcript_path"]))

        self.assertEqual(2, stop_code)
        self.assertIn("agent-relay-attribution", stop_err)
        self.assertEqual("", stop_out)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        body = json.loads(warn_out)
        self.assertEqual("Stop", body["hookSpecificOutput"]["hookEventName"])
        self.assertIn("agent-relay-attribution", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = firing_payload("agent-relay-event-row")
        try:
            with hook_env(CATSTACK_HOOK_MODE_AGENT_RELAY_ATTRIBUTION="warn") as tmp:
                code, err, out = run_claude(payload)
                rows = event_rows(tmp)
        finally:
            os.unlink(str(payload["transcript_path"]))

        finding_rows = [row for row in rows if row["action"] == "warned"]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("agent-relay-attribution", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("agent-relay-attribution.unattributed-relay", finding_rows[0]["rule_id"])
        self.assertEqual("agent-relay-attribution", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])


if __name__ == "__main__":
    unittest.main()
