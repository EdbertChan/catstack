#!/usr/bin/env python3
"""The positive fixtures are the two real tags from the session that motivated
this hook (2026-09-11, NiceSpeak streaming): both were emitted, both ended the
turn, neither left a trace anywhere.
"""
from __future__ import annotations

import os
import sys
import tempfile
import json
import time
import unittest
import warnings
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.dirname(HERE)
LLM_JUDGE = os.path.join(os.path.dirname(HOOK), "llm-judge")
sys.path.insert(0, HOOK)
sys.path.append(LLM_JUDGE)

import judge

REAL_TAG_1 = (
    "{{CAT-UNVERIFIED: that it widened scope past the one session I gave it "
    "-- cannot verify: it never answered when asked twice; its "
    '"21,298,308 tokens / three sessions" line is the only signal}}')
REAL_TAG_2 = (
    "{{CAT-UNVERIFIED: that I told you to plug in the phone because I trusted the status string "
    "-- cannot verify: my own reasoning isn't observable by any command}}")
CLEARABLE_BROWSER_TAG = (
    "{{CAT-UNVERIFIED: browser automation proof "
    "-- cannot verify: browser-only, No browser is available}}")
HUMAN_OAUTH_TAG = (
    "{{CAT-UNVERIFIED: private account linking status "
    "-- cannot verify: requires human-only OAuth consent}}")
MALFORMED = "{{CAT-UNVERIFIED: something I did not check}}"
JUDGE_NOT_CLEARABLE = json.dumps({"match": False, "closest": ""})
PY = sys.executable
SMART_CLEARABLE_SCRIPT = (
    "import json, sys; "
    "prompt = sys.argv[1]; "
    "match = 'No browser is available' in prompt and 'Playwright browser install is present' in prompt; "
    "print(json.dumps({'match': match, 'closest': 'browser evidence present' if match else ''}))"
)
ANSWERS_CLEARABLE = ["fake", [PY, "-c", SMART_CLEARABLE_SCRIPT, "{prompt}"]]
ANSWERS_NOT_CLEARABLE = ["fake", [PY, "-c", f"print({JUDGE_NOT_CLEARABLE!r})", "{prompt}"]]
MISSING_RUNNER = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.judge_state = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "CATSTACK_TAG_LEDGER_DIR": self.tmp.name,
            judge.STATE_ENV: self.judge_state.name,
            judge.RUNNERS_ENV: json.dumps([ANSWERS_CLEARABLE]),
        })
        self.env.start()
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        warnings.simplefilter("ignore", ResourceWarning)
        os.environ.pop(judge.CHILD_ENV, None)
        for module in ("detect", "markers"):
            sys.modules.pop(module, None)
        import detect
        self.detect = detect

    def tearDown(self) -> None:
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.env.stop()
        self.warning_context.__exit__(None, None, None)
        self.judge_state.cleanup()
        self.tmp.cleanup()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.judge_state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def wait_for_no_jobs(self, seconds: float = 15) -> None:
        deadline = time.monotonic() + seconds
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)

    def test_real_tag_is_parsed_into_claim_and_reason(self) -> None:
        tags = self.detect.parse_tags(f"Some prose.\n\n{REAL_TAG_1}")
        self.assertEqual(len(tags), 1)
        self.assertIn("widened scope", tags[0]["claim"])
        self.assertIn("never answered", tags[0]["reason"])

    def test_malformed_tag_is_not_logged(self) -> None:
        self.detect.record_turn("s1", MALFORMED, set())
        self.assertEqual(self.detect.read_ledger("s1"), [])

    def test_message_with_no_tag_leaves_ledger_empty(self) -> None:
        self.detect.record_turn("s1", "Ran the tests, 59/59 pass.", {"Bash"})
        self.assertEqual(self.detect.read_ledger("s1"), [])
        self.assertEqual(self.detect.reminder("s1"), "")

    def test_tag_after_a_real_attempt_is_logged_and_allowed(self) -> None:
        verdict = self.detect.evaluate(
            {"session_id": "s1", "message": REAL_TAG_1, "tools_used": ["Bash"]})
        self.assertEqual(verdict["block"], "")
        self.assertIn("deferred, not discharged", verdict["note"])
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

    def test_tag_with_no_attempt_is_blocked(self) -> None:
        verdict = self.detect.evaluate(
            {"session_id": "s1", "message": REAL_TAG_1, "tools_used": []})
        self.assertIn("ran no verification tool", verdict["block"])
        self.assertIn("cat-mode/SKILL.md:269", verdict["block"])
        self.assertIn("widened scope", verdict["block"])

    def test_blocked_turn_is_still_recorded(self) -> None:
        self.detect.evaluate({"session_id": "s1", "message": REAL_TAG_1, "tools_used": []})
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

    def test_rewrite_turn_is_released_so_the_block_cannot_loop(self) -> None:
        verdict = self.detect.evaluate({
            "session_id": "s1", "message": REAL_TAG_1,
            "tools_used": [], "stop_hook_active": True})
        self.assertEqual(verdict["block"], "")

    def test_untagged_turn_with_no_tools_is_never_blocked(self) -> None:
        verdict = self.detect.evaluate(
            {"session_id": "s1", "message": "Short answer, nothing claimed.", "tools_used": []})
        self.assertEqual(verdict["block"], "")
        self.assertEqual(verdict["note"], "")

    def test_both_real_session_turns_would_have_been_blocked(self) -> None:
        for tag in (REAL_TAG_1, REAL_TAG_2):
            verdict = self.detect.evaluate(
                {"session_id": "replay", "message": f"prose\n\n{tag}", "tools_used": []})
            self.assertIn("ran no verification tool", verdict["block"])

    def test_reminder_names_the_claim_and_cites_the_rule(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        text = self.detect.reminder("s1")
        self.assertIn("widened scope", text)
        self.assertIn("cat-mode/SKILL.md:269", text)
        self.assertIn("never a place to stop", text)

    def test_two_tags_in_one_session_both_tracked(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", REAL_TAG_2, set())
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 2)

    def test_verified_and_dropped_tag_is_discharged(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", "Here is the pasted output proving it.", {"Bash"})
        self.assertEqual(self.detect.outstanding(self.detect.read_ledger("s1")), [])
        self.assertEqual(self.detect.reminder("s1"), "")

    def test_redropping_without_verifying_keeps_it_outstanding(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", "Moving on to something else.", set())
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

    def test_reemitting_the_same_tag_does_not_duplicate_it(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.assertEqual(len(self.detect.read_ledger("s1")), 1)

    def test_stale_tag_escalates_to_reflect(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        for _ in range(self.detect.ESCALATE_AFTER_TURNS):
            self.detect.record_turn("s1", REAL_TAG_1, set())
        self.assertIn("reflect trigger", self.detect.reminder("s1"))

    def test_sessions_do_not_leak_into_each_other(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.assertEqual(self.detect.reminder("s2"), "")

    def test_corrupt_ledger_row_is_reported_not_swallowed(self) -> None:
        path = self.detect.ledger_path("s3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        import io
        from contextlib import redirect_stderr
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            rows = self.detect.read_ledger("s3")
        self.assertEqual(rows, [])
        self.assertIn("is not JSON", buffer.getvalue())

    def test_clearable_browser_blocker_is_reported_on_next_prompt(self) -> None:
        payload = {
            "session_id": "s-browser",
            "message": CLEARABLE_BROWSER_TAG,
            "tools_used": ["Bash"],
            "transcript": [
                {"role": "assistant", "content": "Playwright browser install is present at /ms-playwright/chromium-1234."},
            ],
        }
        self.detect.evaluate(payload)
        self.wait_for_no_jobs()
        text = self.detect.reminder("s-browser")
        self.assertIn("browser automation proof", text)
        self.assertIn("clearable blocker", text)
        self.assertIn("open claim to verify", text)

    def test_human_only_oauth_blocker_does_not_report_clearable_blocker(self) -> None:
        os.environ[judge.RUNNERS_ENV] = json.dumps([ANSWERS_NOT_CLEARABLE])
        self.detect.evaluate({
            "session_id": "s-oauth",
            "message": HUMAN_OAUTH_TAG,
            "tools_used": ["Read"],
            "transcript": [
                {"role": "user", "content": "I have to approve the OAuth consent screen myself."},
            ],
        })
        self.wait_for_no_jobs()
        text = self.detect.reminder("s-oauth")
        self.assertIn("private account linking status", text)
        self.assertNotIn("clearable blocker", text)
        self.assertNotIn("unchecked", text)

    def test_blocker_judge_failure_is_reported_unchecked(self) -> None:
        os.environ[judge.RUNNERS_ENV] = json.dumps([MISSING_RUNNER])
        self.detect.evaluate({
            "session_id": "s-unchecked",
            "message": CLEARABLE_BROWSER_TAG,
            "tools_used": ["Bash"],
            "transcript": [
                {"role": "assistant", "content": "Playwright browser install is present."},
            ],
        })
        self.wait_for_no_jobs()
        text = self.detect.reminder("s-unchecked")
        self.assertIn("browser automation proof", text)
        self.assertIn("blocker judge unchecked", text)
        self.assertNotIn("clearable blocker", text)


if __name__ == "__main__":
    unittest.main()
