#!/usr/bin/env python3
"""The word check reads the turn it runs in: who blocked first, and what
the user asked for.

`stop_hook_active` only says some Stop hook blocked earlier this turn. The
transcript says which one, and what the user typed.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

RUNNER = "/usr/bin/python3 $HOME/.claude/hooks/_runner/run.py --timeout 9.5"
SHEET_BLOCK = (
    f"Stop hook feedback:\n[{RUNNER} spreadsheet-completeness-guard/claude_stop_check.py]: "
    "Do not declare spreadsheet data complete until the expected-entity coverage "
    "validator has passed.\n"
)
WORD_BLOCK = (
    f"Stop hook feedback:\n[{RUNNER} diu-stop/claude_stop_check.py]: "
    "Apply diu: 200 words, over the 150-word guideline. Cut at least 50 words.\n"
)
QUESTION = "so why suggest it again in the second fix?"


def words(count):
    return " ".join(["word"] * count)


def run_check(event):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


class TurnTranscriptCase(JudgeTestCase):
    def transcript(self, prompt, *feedback):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "session.jsonl")
        rows = [
            {"type": "user", "message": {"role": "user", "content": "an earlier question"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": WORD_BLOCK}},
            {"type": "user", "message": {"role": "user", "content": prompt}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "a first draft"}]}},
        ]
        rows.extend(
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": text}}
            for text in feedback)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def check(self, message, prompt, *feedback, retry=None):
        event = {
            "last_assistant_message": message,
            "transcript_path": self.transcript(prompt, *feedback),
            "stop_hook_active": bool(feedback) if retry is None else retry,
        }
        return run_check(event)


class RetryAfterAnotherHooksBlock(TurnTranscriptCase):
    def test_long_reply_after_a_spreadsheet_guard_block_is_still_over_the_limit(self):
        blocked, err = self.check(words(200), "tell me the whole story in detail", SHEET_BLOCK)
        self.assertTrue(blocked)
        self.assertIn("Apply diu: 200 words", err)

    def test_long_reply_after_its_own_word_block_is_allowed_once(self):
        blocked, err = self.check(words(200), "tell me the whole story in detail", WORD_BLOCK)
        self.assertFalse(blocked)
        self.assertNotIn("Apply diu", err)

    def test_own_block_in_an_earlier_turn_does_not_count_for_this_turn(self):
        blocked, err = self.check(words(200), "tell me the whole story in detail", SHEET_BLOCK)
        self.assertTrue(blocked)

    def test_retry_with_no_transcript_is_unchecked_not_clean(self):
        blocked, err = run_check({"last_assistant_message": words(200), "stop_hook_active": True})
        self.assertFalse(blocked)
        self.assertIn("unchecked", err)


class UserWordCap(TurnTranscriptCase):
    def test_reads_each_cap_form_from_the_users_turn(self):
        cases = {
            "explain fix 2 eli5 < 40 words": 40,
            "what is this <25 words please": 25,
            "ok /diu all i want is an answer": 40,
            "Please help me understand ELI5": 40,
            "eli 5 and < 30 words": 30,
            "what does this line do?": None,
        }
        for prompt, cap in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(claude_stop_check.user_word_cap(prompt), cap)

    def test_reply_over_the_users_cap_fires_under_the_default_limit(self):
        blocked, err = self.check(words(60), "we're focusing on fix 2. eli5 < 40 words")
        self.assertTrue(blocked)
        self.assertIn("40", err)
        self.assertIn("lead with the answer", err)

    def test_reply_within_the_users_cap_stays_silent(self):
        blocked, err = self.check(words(35), "we're focusing on fix 2. eli5 < 40 words")
        self.assertFalse(blocked)
        self.assertNotIn("Apply diu", err)

    def test_rewrite_after_own_block_is_rechecked_against_the_users_cap(self):
        blocked, err = self.check(words(90), "eli5 < 40 words", WORD_BLOCK)
        self.assertTrue(blocked)
        self.assertIn("under 40 words", err)

    def test_rewrite_after_two_own_blocks_is_allowed(self):
        blocked, _err = self.check(words(90), "eli5 < 40 words", WORD_BLOCK, WORD_BLOCK)
        self.assertFalse(blocked)


class ShortQuestionRewrite(TurnTranscriptCase):
    def test_long_answer_to_a_short_question_asks_for_a_40_word_rewrite(self):
        blocked, err = self.check(words(160), QUESTION)
        self.assertTrue(blocked)
        self.assertIn("rewrite under 40 words, lead with the answer", err)
        self.assertNotIn("Cut at least", err)

    def test_long_answer_to_a_depth_request_keeps_the_cut_message(self):
        blocked, err = self.check(words(160), "walk me through it step by step in detail")
        self.assertTrue(blocked)
        self.assertIn("Cut at least 10 words", err)
        self.assertNotIn("rewrite under 40 words", err)

    def test_short_answer_to_a_short_question_is_silent(self):
        blocked, err = self.check(words(120), QUESTION)
        self.assertFalse(blocked)
        self.assertNotIn("Apply diu", err)


if __name__ == "__main__":
    unittest.main()
