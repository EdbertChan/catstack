#!/usr/bin/env python3
"""Tests for the hedge-runs-prove-it Stop hook.

Run: python3 -m unittest discover -s engine/hooks/hedge-runs-prove-it/tests -v

Fixtures in tests/fixtures/ are sanitized replies from real sessions
("presumably moving it to catstack" with no check run; "it's a zombie, not
slow" asserted off a capacity projection while ten workers were at 96% CPU)
plus the shapes the rule names. Each fixture carries `verified`: whether the
turn ran a verification tool. The diagnosis fixtures set it true on purpose
-- an unhedged root-cause claim is not cleared by having run a tool, only by
instrument-level proof in the same message.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def turn_lines(verified):
    lines = [{"type": "user", "message": {"role": "user", "content": "what is this file?"}}]
    if verified:
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status --porcelain"}}]}})
    return lines


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_hook(payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestBlocksUnverifiedHedges(unittest.TestCase):
    def test_blocks_each_hedge_fixture(self):
        for case in load("hedges_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_hook_blocks_presumably_reply_with_exit_2(self):
        case = load("hedges_fires.json")[0]
        path = transcript_file(turn_lines(False))
        try:
            code, err = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("prove-it", err)
        self.assertIn("presumably", err)

    def test_blocks_unverified_without_reason_even_with_no_transcript(self):
        self.assertIsNotNone(detect.decide({"last_assistant_message": load("hedges_fires.json")[2]["reply"]}))


class TestAllowsVerifiedOrReasonedHedges(unittest.TestCase):
    def test_allows_each_silent_fixture(self):
        for case in load("hedges_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_allows_hedge_when_read_tool_ran_this_turn(self):
        lines = turn_lines(False) + [{"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/x.py"}}]}}]
        self.assertIsNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_verification_was_in_a_previous_turn_only_if_rerun(self):
        lines = turn_lines(True) + [{"type": "user", "message": {"role": "user", "content": "and now?"}}]
        self.assertIsNotNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"],
            "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


class TestQuotedHedgeSpans(unittest.TestCase):
    """A hedge cited inside a quote run is exempt wherever it sits in the run,
    not only when it is the run's first token."""

    def test_blocks_unquoted_mid_sentence_hedge(self):
        self.assertEqual(
            detect.code_hedges(
                "I might send you the matcher change near a PR; it should work "
                "for the heredoc case in claude.hook.json too."
            ),
            ["should work"],
        )

    def test_no_hit_hedge_quoted_past_the_first_token(self):
        for quote in ('"that should work"', "`that should work`", "'that should work'"):
            with self.subTest(quote=quote):
                self.assertEqual(
                    detect.code_hedges(f"I might send you {quote} near a PR."), []
                )

    def test_no_hit_when_describing_the_hooks_own_triggers(self):
        self.assertEqual(
            detect.code_hedges(
                'The gate fires on `I think`, "that should work", or a bare '
                "`UNVERIFIED:` next to a code noun in the same PR reply."
            ),
            [],
        )

    def test_blocks_hedge_when_apostrophes_are_the_only_single_quotes(self):
        self.assertEqual(
            detect.code_hedges("It's probably still on the branch and I don't think the build ran."),
            ["probably"],
        )

    def test_no_hit_apostrophe_does_not_open_a_span_over_a_possessive(self):
        self.assertEqual(
            detect.code_hedges("The workers' pool probably still holds the stale commit."),
            ["probably"],
        )

    def test_no_hit_after_an_unbalanced_opening_quote(self):
        self.assertEqual(detect.code_hedges('He said "should work for the test suite'), [])

    def test_quoted_spans_ignores_apostrophes(self):
        self.assertEqual(detect.quoted_spans("it's, don't, the workers' pool"), [])


class TestBlocksUnhedgedDiagnosis(unittest.TestCase):
    def test_blocks_each_diagnosis_fixture(self):
        for case in load("diagnosis_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["verified"]))
                )

    def test_blocks_zombie_claim_even_though_the_turn_ran_a_tool(self):
        case = load("diagnosis_fires.json")[0]
        self.assertTrue(detect.diagnosis_claims(case["reply"]))
        self.assertEqual(detect.code_hedges(case["reply"]), [])
        self.assertIsNotNone(detect.decide_from_lines(case["reply"], turn_lines(True)))

    def test_hook_blocks_zombie_claim_with_exit_2(self):
        case = load("diagnosis_fires.json")[0]
        path = transcript_file(turn_lines(True))
        try:
            code, err = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("instrument-level proof", err)
        self.assertIn("zombie", err)

    def test_blocks_diagnosis_with_no_transcript_at_all(self):
        case = load("diagnosis_fires.json")[2]
        self.assertIsNotNone(detect.decide({"last_assistant_message": case["reply"]}))


class TestAllowsProvenOrQuotedDiagnosis(unittest.TestCase):
    def test_allows_each_silent_diagnosis_fixture(self):
        for case in load("diagnosis_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["verified"]))
                )

    def test_no_hit_when_the_process_table_ships_in_the_same_message(self):
        self.assertEqual(detect.diagnosis_claims(load("diagnosis_silent.json")[0]["reply"]), [])

    def test_allows_diagnosis_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("diagnosis_fires.json")[0]["reply"],
            "stop_hook_active": True,
        }))

    def test_diagnosis_gate_ignores_an_unreadable_transcript(self):
        self.assertIsNotNone(detect.decide({
            "last_assistant_message": load("diagnosis_fires.json")[0]["reply"],
            "transcript_path": "/nonexistent/x.jsonl",
        }))


if __name__ == "__main__":
    unittest.main()
