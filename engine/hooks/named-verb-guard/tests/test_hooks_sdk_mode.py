#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE.parent
LLM_JUDGE_DIR = HOOK_DIR.parent / "llm-judge"
sys.path.insert(0, str(LLM_JUDGE_DIR))

import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

ENTRYPOINT = HOOK_DIR / "claude_stop_check.py"
PY = sys.executable
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": "test it"})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
SLOW_HIT = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
BARE_PASS = "Fixed it and ran the tests. See https://example.com/build. Ran `rm tmp`."


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


def run_entrypoint(payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged,
    )


class NamedVerbGuardSdkModeTest(JudgeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.use_runners(ANSWERS_HIT)

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        jobs = Path(self.state.name) / "jobs"
        while jobs.is_dir() and any(jobs.iterdir()) and time.monotonic() < deadline:
            time.sleep(0.05)
        super().tearDown()

    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        result = run_entrypoint(
            self._event("test it", BARE_PASS),
            {"CATSTACK_HOOK_MODE_NAMED_VERB_GUARD": "warn"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        self.assertIn(
            phrases.load("named-verb-guard-prove-request")["on_hit"],
            rendered["hookSpecificOutput"]["additionalContext"],
        )
        rows = self._finding_rows()
        self.assertEqual(["named-verb-guard.prove-request"], [row["rule_id"] for row in rows])
        self.assertEqual(["warned"], [row["action"] for row in rows])
        self.assertEqual(["override"], [row["mode_source"] for row in rows])

    def test_mode_stop_blocks_by_default(self) -> None:
        result = run_entrypoint(self._event("test it", BARE_PASS), {})

        self.assertEqual(2, result.returncode)
        self.assertIn(phrases.load("named-verb-guard-prove-request")["on_hit"], result.stderr)

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        result = run_entrypoint(
            self._event("test it", BARE_PASS, session_id="named-verb-event-row"),
            {"CATSTACK_HOOK_MODE_NAMED_VERB_GUARD": "warn"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        rows = self._finding_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual("named-verb-guard", rows[0]["hook"])
        self.assertEqual("named-verb-guard.prove-request", rows[0]["rule_id"])
        self.assertEqual("warned", rows[0]["action"])

    def test_late_verdict_records_unchecked_and_allows_reply(self) -> None:
        self.use_runners(SLOW_HIT)
        result = run_entrypoint(
            self._event("test it", BARE_PASS, session_id="named-verb-timeout"),
            {"CATSTACK_NAMED_VERB_GUARD_WAIT_SECONDS": "0.1"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("unchecked", result.stderr)
        self.assertEqual("", result.stdout)
        rows = self._finding_rows()
        self.assertEqual(["unchecked"], [row["action"] for row in rows])
        self.assertEqual(["named-verb-guard.prove-request"], [row["rule_id"] for row in rows])

    def _event(self, user_text: str, reply: str, session_id: str = "named-verb-sdk-mode") -> dict[str, object]:
        path = Path(self.work.name) / f"{session_id}.jsonl"
        path.write_text(transcript_line("user", user_text) + "\n", encoding="utf-8")
        return {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "transcript_path": str(path),
            "last_assistant_message": reply,
        }

    def _finding_rows(self) -> list[dict[str, object]]:
        root = Path(os.environ["CATSTACK_HOOK_METRICS_DIR"])
        rows = [
            json.loads(line)
            for file in root.glob("events-*.jsonl")
            for line in file.read_text(encoding="utf-8").splitlines()
        ]
        return [row for row in rows if row.get("rule_id") == "named-verb-guard.prove-request"]


if __name__ == "__main__":
    unittest.main()
