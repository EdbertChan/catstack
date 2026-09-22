#!/usr/bin/env python3
"""The positive fixtures are the two real tags from the session that motivated
this hook (2026-09-11, NiceSpeak streaming): both were emitted, both ended the
turn, neither left a trace anywhere.

`fixtures/claude-stop-payload.json` and `fixtures/claude-transcript.jsonl` are
captured from a live Claude Code run, not written by hand. Hand-written
payloads are what let this hook read `tools_used` -- a key Claude Code has
never sent -- for its whole life: every test supplied the key itself, so the
suite stayed green over a branch that could not run. `test_payload_contract...`
below is the catch: every key `detect.py` reads off the payload has to exist
in the captured one.
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
REAL_PAYLOAD = os.path.join(FIXTURES, "claude-stop-payload.json")
REAL_TRANSCRIPT = os.path.join(FIXTURES, "claude-transcript.jsonl")
sys.path.insert(0, HOOK)

REAL_TAG_1 = (
    "{{CAT-UNVERIFIED: that it widened scope past the one session I gave it "
    "-- cannot verify: it never answered when asked twice; its "
    '"21,298,308 tokens / three sessions" line is the only signal}}')
REAL_TAG_2 = (
    "{{CAT-UNVERIFIED: that I told you to plug in the phone because I trusted the status string "
    "-- cannot verify: my own reasoning isn't observable by any command}}")
MALFORMED = "{{CAT-UNVERIFIED: something I did not check}}"

EVIDENCE_ORDER_1 = "Correcting one claim and arming the check I implied:"
EVIDENCE_ORDER_2 = "I was right - but I said it a turn before I checked it"


def _real_transcript_lines() -> list[str]:
    with open(REAL_TRANSCRIPT, encoding="utf-8") as handle:
        return [line for line in handle if line.strip()]


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

    def transcript(self, *, tools: bool, name: str = "transcript.jsonl") -> str:
        """A real captured transcript, optionally with its tool_use line cut."""
        lines = _real_transcript_lines()
        if not tools:
            lines = [line for line in lines if '"tool_use"' not in line]
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        return path

    def payload(self, message: str, *, tools: bool, **extra) -> dict:
        """A Stop payload with exactly the keys the captured one has."""
        data = {
            "session_id": "s1",
            "last_assistant_message": message,
            "transcript_path": self.transcript(tools=tools),
        }
        data.update(extra)
        return data

    def test_payload_contract_every_key_detect_reads_exists_in_a_real_payload(self) -> None:
        """Every `payload.get("k")` in detect.py must be a key Claude Code sends."""
        with open(os.path.join(HOOK, "detect.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        keys = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "payload"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
        self.assertTrue(keys, "found no payload.get() calls to check")
        with open(REAL_PAYLOAD, encoding="utf-8") as handle:
            real = json.load(handle)
        missing = sorted(key for key in keys if key not in real)
        self.assertEqual(
            missing, [],
            f"detect.py reads {missing} but a real Claude Code Stop payload has "
            f"only {sorted(real)}")

    def test_real_payload_carries_no_tool_list_of_any_kind(self) -> None:
        """The regression this hook shipped with: there is no tools_used key."""
        with open(REAL_PAYLOAD, encoding="utf-8") as handle:
            real = json.load(handle)
        self.assertNotIn("tools_used", real)
        self.assertNotIn("tool_names", real)
        self.assertIn("transcript_path", real)

    def test_tools_are_read_from_the_real_transcript(self) -> None:
        tools = self.detect.tools_used_this_turn(
            {"transcript_path": self.transcript(tools=True)})
        self.assertEqual(tools, {"Bash"})

    def test_a_turn_with_no_tool_use_reads_as_an_empty_set_not_none(self) -> None:
        tools = self.detect.tools_used_this_turn(
            {"transcript_path": self.transcript(tools=False)})
        self.assertEqual(tools, set())

    def test_a_missing_transcript_reads_as_unchecked_and_says_so(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            tools = self.detect.tools_used_this_turn(
                {"transcript_path": os.path.join(self.tmp.name, "nope.jsonl")})
        self.assertIsNone(tools)
        self.assertIn("unchecked", buffer.getvalue())

    def test_a_payload_with_no_transcript_path_reads_as_unchecked(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            tools = self.detect.tools_used_this_turn({"session_id": "s1"})
        self.assertIsNone(tools)
        self.assertIn("unchecked", buffer.getvalue())

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
        verdict = self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        self.assertEqual(verdict["block"], "")
        self.assertIn("deferred, not discharged", verdict["note"])
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

    def test_tag_with_no_attempt_is_blocked(self) -> None:
        verdict = self.detect.evaluate(self.payload(REAL_TAG_1, tools=False))
        self.assertIn("ran no verification tool", verdict["block"])
        self.assertIn("cat-mode/SKILL.md:269", verdict["block"])
        self.assertIn("widened scope", verdict["block"])

    def test_blocked_turn_is_still_recorded(self) -> None:
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=False))
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

    def test_rewrite_turn_is_released_so_the_block_cannot_loop(self) -> None:
        verdict = self.detect.evaluate(
            self.payload(REAL_TAG_1, tools=False, stop_hook_active=True))
        self.assertEqual(verdict["block"], "")

    def test_untagged_turn_with_no_tools_is_never_blocked(self) -> None:
        verdict = self.detect.evaluate(
            self.payload("Short answer, nothing claimed.", tools=False))
        self.assertEqual(verdict["block"], "")
        self.assertEqual(verdict["note"], "")

    def test_both_real_session_turns_would_have_been_blocked(self) -> None:
        for tag in (REAL_TAG_1, REAL_TAG_2):
            verdict = self.detect.evaluate(
                self.payload(f"prose\n\n{tag}", tools=False, session_id="replay"))
            self.assertIn("ran no verification tool", verdict["block"])

    def test_an_unreadable_turn_is_neither_blocked_nor_called_clean(self) -> None:
        verdict = self.detect.evaluate({
            "session_id": "s1", "last_assistant_message": REAL_TAG_1,
            "transcript_path": os.path.join(self.tmp.name, "gone.jsonl")})
        self.assertEqual(verdict["block"], "")
        self.assertIn("UNCHECKED", verdict["note"])

    def test_reminder_names_the_claim_and_cites_the_rule(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        text = self.detect.reminder("s1", "all")
        self.assertIn("widened scope", text)
        self.assertIn("cat-mode/SKILL.md:269", text)
        self.assertIn("never a place to stop", text)

    def test_reminder_is_silent_on_off(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        for _ in range(self.detect.ESCALATE_AFTER_TURNS):
            self.detect.record_turn("s1", REAL_TAG_1, set())
        self.assertEqual(self.detect.reminder("s1", "off"), "")

    def test_a_young_claim_is_not_reinjected_by_default(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", REAL_TAG_1, set())
        rows = self.detect.read_ledger("s1")
        self.assertEqual(rows[0]["turns"], 1)
        self.assertEqual(self.detect.reminder("s1"), "")

    def test_a_claim_that_survives_three_turns_is_reinjected_by_default(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        for _ in range(self.detect.ESCALATE_AFTER_TURNS):
            self.detect.record_turn("s1", REAL_TAG_1, set())
        text = self.detect.reminder("s1")
        self.assertIn("widened scope", text)
        self.assertIn("reflect trigger", text)

    def test_an_unset_flag_resolves_to_stale_not_to_the_old_behaviour(self) -> None:
        mode, note = self.detect.reminder_mode(environ={}, cwd=None, home=self.tmp.name)
        self.assertEqual(mode, "stale")
        self.assertEqual(note, "")

    def test_each_flag_value_is_honoured(self) -> None:
        for value in ("off", "stale", "all"):
            mode, _note = self.detect.reminder_mode(
                environ={self.detect.REMINDER_FLAG: value}, cwd=None, home=self.tmp.name)
            self.assertEqual(mode, value)

    def test_a_flag_value_nobody_understands_says_so_and_falls_back(self) -> None:
        mode, note = self.detect.reminder_mode(
            environ={self.detect.REMINDER_FLAG: "quiet"}, cwd=None, home=self.tmp.name)
        self.assertEqual(mode, "stale")
        self.assertIn("is not off, stale, all", note)

    def test_an_unreadable_env_file_is_reported_as_unchecked(self) -> None:
        unreadable = os.path.join(self.tmp.name, "env-is-a-directory")
        os.makedirs(unreadable, exist_ok=True)
        mode, note = self.detect.reminder_mode(
            environ={"CATSTACK_ENV_FILE": unreadable}, cwd=None, home=self.tmp.name)
        self.assertEqual(mode, "stale")
        self.assertIn("could not read", note)

    def test_recording_keeps_happening_while_the_reminder_is_off(self) -> None:
        """off is about the injection, never about the ledger."""
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)
        self.assertEqual(self.detect.reminder("s1", "off"), "")

    def test_two_tags_in_one_session_both_tracked(self) -> None:
        self.detect.record_turn("s1", REAL_TAG_1, set())
        self.detect.record_turn("s1", REAL_TAG_2, set())
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 2)

    def test_verified_and_dropped_tag_is_discharged_through_the_real_payload(self) -> None:
        """The branch that could never be reached: a live payload discharges."""
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)
        self.detect.evaluate(self.payload("Here is the pasted output proving it.", tools=True))
        self.assertEqual(self.detect.outstanding(self.detect.read_ledger("s1")), [])
        self.assertEqual(self.detect.reminder("s1"), "")

    def test_a_discharged_claim_fires_the_reflect_trigger(self) -> None:
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        verdict = self.detect.evaluate(
            self.payload("Here is the pasted output proving it.", tools=True))
        self.assertIn("reflect trigger", verdict["note"])
        self.assertIn("widened scope", verdict["note"])

    def test_an_evidence_order_correction_triggers_with_no_wrongness_word(self) -> None:
        """The transition fires; the reply's wording is not consulted at all."""
        for index, reply in enumerate((EVIDENCE_ORDER_1, EVIDENCE_ORDER_2)):
            session = f"evidence-order-{index}"
            self.detect.evaluate(self.payload(REAL_TAG_1, tools=True, session_id=session))
            verdict = self.detect.evaluate(
                self.payload(reply, tools=True, session_id=session))
            self.assertIn("reflect trigger", verdict["note"])
            self.assertIn("carries no wrongness word", verdict["note"])

    def test_a_turn_that_discharges_nothing_stays_silent_about_reflect(self) -> None:
        verdict = self.detect.evaluate(
            self.payload("Ran the tests, all green.", tools=True))
        self.assertEqual(verdict["note"], "")

    def test_a_reemitted_tag_is_not_reported_as_discharged(self) -> None:
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        verdict = self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        self.assertNotIn("reflect trigger", verdict["note"])

    def test_unchecked_turn_does_not_discharge_a_row(self) -> None:
        self.detect.evaluate(self.payload(REAL_TAG_1, tools=True))
        self.detect.evaluate({
            "session_id": "s1", "last_assistant_message": "Moving on.",
            "transcript_path": os.path.join(self.tmp.name, "gone.jsonl")})
        self.assertEqual(len(self.detect.outstanding(self.detect.read_ledger("s1"))), 1)

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
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            rows = self.detect.read_ledger("s3")
        self.assertEqual(rows, [])
        self.assertIn("is not JSON", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
