#!/usr/bin/env python3
"""Tests for make-pr's description check: claims about the repo's past are banned.

A fake `ask` stands in for the judge, so no test calls a real model.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import description_check  # noqa: E402
import preflight  # noqa: E402

BODY = "## Summary\n\nThe check now reads the PR description.\n\n## Review Lane\n\nbehavior\n"


def answering(match: bool, closest: str = ""):
    prompts: list[str] = []

    def ask(prompt: str) -> dict:
        prompts.append(prompt)
        return {"outcome": "answered", "runner": "fake", "answer": {"match": match, "closest": closest}, "attempts": []}

    ask.prompts = prompts
    return ask


def silent(prompt: str) -> dict:
    return {"outcome": "unchecked", "runner": None, "answer": None,
            "attempts": [{"runner": "fake", "reason": "timed out"}]}


class TestDescriptionCheck(unittest.TestCase):
    def test_history_claim_fires_and_names_the_rule(self):
        outcome, lines = description_check.check(BODY, ask=answering(True, "It first broke at a1b2c3d."))
        self.assertEqual(outcome, "hit")
        self.assertTrue(any(line.startswith("hit") and "a1b2c3d" in line for line in lines), lines)
        self.assertIn("banned from PR descriptions", lines[-1])

    def test_description_without_history_claims_is_clean(self):
        ask = answering(False)
        outcome, lines = description_check.check(BODY, ask=ask)
        self.assertEqual(outcome, "clean")
        self.assertEqual(lines, [])
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("The check now reads the PR description.", ask.prompts[0])

    def test_no_runner_answering_is_unchecked_not_clean(self):
        outcome, lines = description_check.check(BODY, ask=silent)
        self.assertEqual(outcome, "unchecked")
        self.assertIn("timed out", lines[0])

    def test_hit_outranks_unchecked(self):
        calls = iter([silent(""), answering(True)("")])
        long_body = "## A\n\n" + "a" * 3000 + "\n## B\n\n" + "b" * 3000
        outcome, _ = description_check.check(long_body, ask=lambda prompt: next(calls))
        self.assertEqual(outcome, "hit")

    def test_long_description_is_split_so_the_top_is_never_clipped(self):
        long_body = "## Summary\n\nfirst claim here\n\n" + "## Test Plan\n\n" + "x" * 5000
        pieces = description_check.chunks(long_body)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= description_check.CHUNK_LIMIT for piece in pieces))
        self.assertIn("first claim here", pieces[0])

    def test_dictionary_loads_with_the_checker_name(self):
        phrases = description_check._load("llm_judge_phrases", "phrases.py")
        dictionary = phrases.load(description_check.CHECKER)
        self.assertEqual(dictionary["checker"], "pr-description-history-claims")

    def test_unreadable_body_file_exits_2(self):
        self.assertEqual(description_check.main(["/nonexistent/body.md"]), 2)


class TestPreflightDescription(unittest.TestCase):
    def test_missing_body_file_fails_as_unchecked(self):
        out = io.StringIO()
        with redirect_stdout(out):
            status = preflight.describe(None)
        self.assertEqual(status, 1)
        self.assertIn("description unchecked", out.getvalue())

    def test_unreadable_body_file_fails_as_unchecked(self):
        out = io.StringIO()
        with redirect_stdout(out):
            status = preflight.describe("/nonexistent/body.md")
        self.assertEqual(status, 1)
        self.assertIn("cannot read", out.getvalue())

    def test_clean_body_file_passes(self):
        original = description_check.check
        description_check.check = lambda body: ("clean", [])
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
                handle.write(BODY)
            out = io.StringIO()
            with redirect_stdout(out):
                status = preflight.describe(handle.name)
        finally:
            description_check.check = original
            os.unlink(handle.name)
        self.assertEqual(status, 0)
        self.assertIn("description clean", out.getvalue())


if __name__ == "__main__":
    unittest.main()
