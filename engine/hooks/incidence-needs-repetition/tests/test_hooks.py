#!/usr/bin/env python3
"""Tests for the incidence-needs-repetition Stop hook.

Run: python3 -m unittest discover -s engine/hooks/incidence-needs-repetition/tests -v

The fires/silent fixtures are the real replies from the 2026-09-09 session
that motivated the hook: the bad one asserted "Deterministic" off a single
run and carried a figure that had never been measured, and the good one is
the repro output that replaced it.
"""
from __future__ import annotations

import io
import json
import os
import sys
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


def assistant_bash(command):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}]},
    }


HUMAN = {"type": "user", "message": {"content": [{"type": "text", "text": "check it"}]}}


class TestBlocksSingleRunIncidenceClaims(unittest.TestCase):
    def test_blocks_each_fires_fixture(self):
        for case in load("incidence_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertTrue(detect.decide_from_lines(case["reply"], []))

    def test_bare_file_line_is_not_repetition_evidence(self):
        reply = "It holds on every run - see packages/data-store/src/x.test.ts:74."
        self.assertTrue(detect.decide_from_lines(reply, []))

    def test_one_invocation_does_not_clear_the_claim(self):
        lines = [HUMAN, assistant_bash("node repro.mjs")]
        self.assertTrue(detect.decide_from_lines("The instrument is deterministic.", lines))

    def test_two_different_commands_are_not_repetition(self):
        lines = [HUMAN, assistant_bash("node repro.mjs"), assistant_bash("pnpm test")]
        self.assertTrue(detect.decide_from_lines("The instrument is deterministic.", lines))

    def test_hook_exits_2_on_a_single_run_claim(self):
        payload = {"last_assistant_message": "Deterministic - 2.44MB against a 1MB threshold."}
        stderr = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    claude_stop_check.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("incidence-needs-repetition", stderr.getvalue())


class TestAllowsMeasuredOrUnasserted(unittest.TestCase):
    def test_allows_each_silent_fixture(self):
        for case in load("incidence_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide_from_lines(case["reply"], []))

    def test_same_command_twice_clears_the_claim(self):
        lines = [HUMAN, assistant_bash("node repro.mjs"), assistant_bash("node repro.mjs")]
        self.assertIsNone(detect.decide_from_lines("The instrument is deterministic.", lines))

    def test_quoted_incidence_word_is_not_a_claim(self):
        self.assertEqual(detect.incidence_claims('The body says "deterministic" but I have not checked.'), [])

    def test_no_incidence_word_is_out_of_scope(self):
        self.assertIsNone(detect.decide_from_lines("Landed the stack; #12036 is blocked on review.", []))


class TestFailsOpen(unittest.TestCase):
    def test_stop_hook_active_skips(self):
        self.assertIsNone(detect.decide({"stop_hook_active": True, "last_assistant_message": "It is deterministic."}))

    def test_missing_transcript_fails_open(self):
        payload = {"last_assistant_message": "It is deterministic.", "transcript_path": "/nonexistent/x.jsonl"}
        self.assertIsNone(detect.decide(payload))

    def test_unparseable_stdin_allows_the_reply(self):
        with patch.object(sys, "stdin", io.StringIO("not json")):
            claude_stop_check.main()


if __name__ == "__main__":
    unittest.main()
