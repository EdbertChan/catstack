#!/usr/bin/env python3
"""Tests for the restated-constraint UserPromptSubmit hook.

Run: python3 -m unittest discover -s engine/hooks/restated-constraint/tests -v

Fixture texts are paraphrased shapes of a real session where the user had
to re-state "stock-agnostic", "one parser per form type", and "never invent
values" several turns apart. Positive cases fire; negative cases stay silent.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402


def transcript_with(user_texts):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for i, text in enumerate(user_texts):
        tmp.write(json.dumps({
            "type": "user",
            "timestamp": f"2000-01-01T00:{i:02d}:00Z",
            "message": {"role": "user", "content": text},
        }) + "\n")
        tmp.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        }) + "\n")
    tmp.close()
    return tmp.name


def run_hook(prompt, transcript_path):
    payload = {"prompt": prompt, "transcript_path": transcript_path, "hook_event_name": "UserPromptSubmit"}
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out):
            claude_prompt_submit.main()
    raw = out.getvalue().strip()
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"] if raw else None


class TestFires(unittest.TestCase):
    def test_hyphenated_term_restated_with_must_fires(self):
        path = transcript_with([
            "make the holdings sheet stock agnostic, it should work for any ticker",
            "looks good, now add the QoQ chart",
        ])
        try:
            context = run_hook(
                "the parser must stay stock-agnostic. no ticker names in the code path.", path,
            )
            self.assertIsNotNone(context)
            self.assertIn("turn 1", context)
            self.assertIn("shared-hyphenated-term", context)
        finally:
            os.unlink(path)

    def test_same_constraint_clause_restated_fires(self):
        path = transcript_with([
            "do not invent values for the cost basis column. leave it blank if the filing lacks it.",
            "what does the 13F say about the June sale",
        ])
        try:
            context = run_hook(
                "I told you already: never invent values in the cost basis, pull them from the filing or leave blank",
                path,
            )
            self.assertIsNotNone(context)
            self.assertIn("turn 1", context)
        finally:
            os.unlink(path)

    def test_one_parser_per_form_type_restated_fires(self):
        path = transcript_with([
            "there must be exactly one parser per form type, don't add a second 13F parser",
        ])
        try:
            context = run_hook(
                "again: one parser per form type. delete the duplicate 13F parser you just added.", path,
            )
            self.assertIsNotNone(context)
        finally:
            os.unlink(path)

    def test_verbatim_resend_of_constraint_fires(self):
        text = "don't hardcode the ticker list, read it from the holdings sheet"
        path = transcript_with([text, "ok now regenerate"])
        try:
            context = run_hook(text, path)
            self.assertIsNotNone(context)
            self.assertIn("turn 1", context)
        finally:
            os.unlink(path)


class TestStaysSilent(unittest.TestCase):
    def test_first_time_constraint_is_silent(self):
        path = transcript_with(["generate the uber equity report going back to all time"])
        try:
            self.assertIsNone(run_hook("the parser must stay stock-agnostic from now on", path))
        finally:
            os.unlink(path)

    def test_prompt_without_constraint_verb_is_silent(self):
        path = transcript_with(["the parser must stay stock-agnostic"])
        try:
            self.assertIsNone(run_hook("how does the stock-agnostic parser pick the form type?", path))
        finally:
            os.unlink(path)

    def test_shared_topic_without_prior_constraint_is_silent(self):
        path = transcript_with(["generate the uber report and show me the portfolio"])
        try:
            self.assertIsNone(run_hook("don't forget the uber report needs the Q2 buyback row", path))
        finally:
            os.unlink(path)

    def test_macro_resent_three_times_is_silent(self):
        text = "briefly summarize, then implement. you must run the tests before claiming done."
        path = transcript_with([text, "fine", text, "fine", text, "fine"])
        try:
            self.assertIsNone(run_hook(text, path))
        finally:
            os.unlink(path)

    def test_generic_hyphenated_word_alone_is_silent(self):
        path = transcript_with(["add the to-do list and a follow-up note to the report"])
        try:
            self.assertIsNone(run_hook("you must keep the to-do list out of the follow-up section", path))
        finally:
            os.unlink(path)

    def test_template_prompt_with_three_near_duplicates_is_silent(self):
        path = transcript_with([
            "implement the next to-do item, you must run tests, then commit and report",
            "implement the next to-do item; you must run tests, commit, and report back",
            "implement the next to-do, you must run the tests and commit then report",
        ])
        try:
            self.assertIsNone(run_hook("implement the next to-do item, you must run tests and commit, report", path))
        finally:
            os.unlink(path)

    def test_current_prompt_already_in_transcript_is_not_self_matched(self):
        text = "never invent values for the cost basis column"
        path = transcript_with([text])
        try:
            self.assertIsNone(run_hook(text, path))
        finally:
            os.unlink(path)

    def test_hook_feedback_and_tool_result_lines_are_ignored(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        tmp.write(json.dumps({"type": "user", "message": {"role": "user", "content":
            "Stop hook feedback: the parser must stay stock-agnostic per CLAUDE.md"}}) + "\n")
        tmp.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "the parser must stay stock-agnostic"}]}}) + "\n")
        tmp.close()
        try:
            self.assertIsNone(run_hook("the parser must stay stock-agnostic, no ticker names", tmp.name))
        finally:
            os.unlink(tmp.name)

    def test_missing_transcript_fails_open(self):
        self.assertIsNone(run_hook("the parser must stay stock-agnostic, no ticker names", "/nonexistent/x.jsonl"))

    def test_garbage_stdin_prints_nothing(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stdout(out):
                claude_prompt_submit.main()
        self.assertEqual(out.getvalue(), "")


class TestDetectUnits(unittest.TestCase):
    def test_kernels_extract_content_words_after_the_verb(self):
        self.assertIn(frozenset({"invent", "values"}), detect.kernels("never invent values here"))

    def test_hyphen_terms_normalize_to_spaces_and_drop_generic_words(self):
        self.assertEqual(detect.hyphen_terms("keep it Stock-Agnostic, re-run the to-do"), {"stock agnostic"})


if __name__ == "__main__":
    unittest.main()
