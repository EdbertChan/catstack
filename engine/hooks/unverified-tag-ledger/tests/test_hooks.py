#!/usr/bin/env python3
"""The positive fixtures are the two real tags from the session that motivated
this hook (2026-09-11, NiceSpeak streaming): both were emitted, both ended the
turn, neither left a trace anywhere.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.dirname(HERE)
sys.path.insert(0, HOOK)

REAL_TAG_1 = (
    "{{CAT-UNVERIFIED: that it widened scope past the one session I gave it "
    "-- cannot verify: it never answered when asked twice; its "
    '"21,298,308 tokens / three sessions" line is the only signal}}')
REAL_TAG_2 = (
    "{{CAT-UNVERIFIED: that I told you to plug in the phone because I trusted the status string "
    "-- cannot verify: my own reasoning isn't observable by any command}}")
MALFORMED = "{{CAT-UNVERIFIED: something I did not check}}"


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CATSTACK_TAG_LEDGER_DIR"] = self.tmp.name
        for module in ("detect", "markers"):
            sys.modules.pop(module, None)
        import detect
        self.detect = detect

    def tearDown(self) -> None:
        os.environ.pop("CATSTACK_TAG_LEDGER_DIR", None)
        self.tmp.cleanup()

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


if __name__ == "__main__":
    unittest.main()
