#!/usr/bin/env python3
"""Tests for wrong-check-reflect.

Run: python3 -m unittest discover -s engine/hooks/wrong-check-reflect/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def run_cursor(payload: dict) -> dict:
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out):
            cursor_session.main()
    return json.loads(out.getvalue() or "{}")


def run_codex_notify(argv: list[str]) -> str:
    err = io.StringIO()
    with patch.object(sys, "argv", ["codex_notify.py", *argv]):
        with redirect_stderr(err):
            codex_notify.main()
    return err.getvalue()


class TestFindAdmission(unittest.TestCase):
    def test_hit_good_catch_earlier_check_was_wrong(self):
        match = detect.find_admission(
            "Good catch — my earlier check was wrong. The real file is elsewhere."
        )
        self.assertIsNotNone(match)
        self.assertIn("earlier check was wrong", match.lower())

    def test_hit_youre_right_i_misread(self):
        self.assertIsNotNone(
            detect.find_admission("You're right, I misread the file.")
        )

    def test_hit_incorrectly_assumed(self):
        self.assertIsNotNone(
            detect.find_admission("I incorrectly assumed that was the source.")
        )

    def test_hit_previous_grep_was_wrong(self):
        self.assertIsNotNone(
            detect.find_admission("my previous grep was wrong — that path is dead.")
        )

    def test_hit_file_i_cited_was_duplicate(self):
        self.assertIsNotNone(
            detect.find_admission("the file I cited was a duplicate.")
        )

    def test_hit_my_mistake_misread_own_skill(self):
        self.assertIsNotNone(
            detect.find_admission(
                "My mistake — the skill does have "
                "disable-model-invocation: true (I misread it), so "
                "fires_example.md needs the literal invocation string."
            )
        )

    def test_hit_i_misread_without_youre_right_prefix(self):
        self.assertIsNotNone(
            detect.find_admission("I misread the front matter on that skill.")
        )

    def test_no_hit_product_test_was_wrong(self):
        self.assertIsNone(detect.find_admission("the test was wrong"))

    def test_no_hit_hypothetical(self):
        self.assertIsNone(
            detect.find_admission("if my earlier check was wrong we'd see X")
        )

    def test_no_hit_hypothetical_my_mistake(self):
        self.assertIsNone(
            detect.find_admission("if that turns out to be my mistake, I'll fix it")
        )

    def test_no_hit_hypothetical_misread(self):
        self.assertIsNone(
            detect.find_admission("if I misread this, let me know")
        )

    def test_no_hit_good_catch_alone(self):
        self.assertIsNone(detect.find_admission("Good catch"))

    def test_no_hit_inside_code_fence(self):
        text = (
            "Here is the pattern:\n"
            "```\n"
            "Good catch — my earlier check was wrong\n"
            "```\n"
            "That is what the detector looks for."
        )
        self.assertIsNone(detect.find_admission(text))

    def test_no_hit_empty(self):
        self.assertIsNone(detect.find_admission(""))
        self.assertIsNone(detect.find_admission(None))  # type: ignore[arg-type]

    def test_hit_unquoted_admission_still_fires(self):
        match = detect.find_admission(
            "Real talk: my earlier check was wrong, the endpoint moved."
        )
        self.assertIsNotNone(match)
        self.assertIn("earlier check was wrong", match.lower())

    def test_no_hit_quoted_readme_example(self):
        text = (
            'wrong-check-reflect fired on quoted example phrases in that '
            "hook's README, not a real admission. It catches things like "
            '"Good catch — my earlier check was wrong" when that text is '
            "actually being cited, not asserted."
        )
        self.assertIsNone(detect.find_admission(text))

    def test_no_hit_backtick_quoted_phrase(self):
        text = (
            "The regex looks for phrases like `my earlier check was wrong` "
            "in assistant text -- describing the pattern, not admitting one."
        )
        self.assertIsNone(detect.find_admission(text))

    def test_hit_reversed_word_order_labeled_without_verifying_at_the_time(self):
        match = detect.find_admission(
            "I read that wrong in my earlier summary table (labeled them "
            "ready without actually verifying status at the time). "
            "Confirmed now."
        )
        self.assertIsNotNone(match)

    def test_no_hit_normal_correction_language(self):
        self.assertIsNone(
            detect.find_admission(
                "Let me also check the summary table before confirming -- "
                "I'll verify this next."
            )
        )

    def test_no_hit_hypothetical_reversed_word_order(self):
        self.assertIsNone(
            detect.find_admission(
                "If I read that wrong in my earlier note, let me know and "
                "I'll recheck."
            )
        )


class TestDecideOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["WRONG_CHECK_REFLECT_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_fires_then_stays_silent(self):
        path = os.path.join(self.tmp.name, "sess.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": "Good catch — my earlier check was wrong",
                        },
                    }
                )
                + "\n"
            )
        first = detect.decide(
            {
                "transcript_path": path,
                "last_assistant_message": "Good catch — my earlier check was wrong",
            }
        )
        self.assertIsNotNone(first)
        self.assertIn("FAILURE", first)
        self.assertIn("reflect", first.lower())
        self.assertIn(path, first)
        second = detect.decide(
            {
                "transcript_path": path,
                "last_assistant_message": "Good catch — my earlier check was wrong",
            }
        )
        self.assertIsNone(second)

    def test_user_already_said_reflect_skips(self):
        path = os.path.join(self.tmp.name, "asked.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "please /reflect"},
                    }
                )
                + "\n"
            )
        self.assertIsNone(
            detect.decide(
                {
                    "transcript_path": path,
                    "last_assistant_message": "my earlier check was wrong",
                }
            )
        )

    def test_stop_hook_active_skips(self):
        self.assertIsNone(
            detect.decide(
                {
                    "stop_hook_active": True,
                    "last_assistant_message": "my earlier check was wrong",
                }
            )
        )

    def test_clean_does_not_prompt(self):
        self.assertIsNone(
            detect.decide({"last_assistant_message": "I'll check the logs next."})
        )


class TestHarnessWrappers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["WRONG_CHECK_REFLECT_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_blocks_on_admission(self):
        blocked, err = run_claude(
            {"last_assistant_message": "Good catch — my earlier check was wrong"}
        )
        self.assertTrue(blocked)
        self.assertIn("FAILURE", err)
        self.assertIn("reflect", err.lower())

    def test_claude_allows_clean(self):
        blocked, err = run_claude({"last_assistant_message": "short reply"})
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_claude_malformed_stdin_fail_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_cursor_followup_on_admission(self):
        body = run_cursor(
            {"last_assistant_message": "You're right, I misread the file."}
        )
        self.assertIn("FAILURE", body.get("followup_message", ""))

    def test_cursor_empty_on_clean(self):
        body = run_cursor({"last_assistant_message": "all good"})
        self.assertEqual(body.get("followup_message"), "")

    def test_cursor_malformed_stdin_fail_open(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stdout(out):
                cursor_session.main()
        self.assertEqual(json.loads(out.getvalue()).get("followup_message"), "")

    def test_codex_prints_on_admission(self):
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "last-assistant-message": "I incorrectly assumed that was the source.",
            }
        )
        out = run_codex_notify([payload])
        self.assertIn("wrong-check-reflect", out)

    def test_codex_silent_on_clean(self):
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "last-assistant-message": "short reply",
            }
        )
        self.assertEqual(run_codex_notify([payload]), "")

    def test_codex_still_chains(self):
        chain = os.path.join(self.tmp.name, "chain.sh")
        marker = os.path.join(self.tmp.name, "chained")
        with open(chain, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\necho ok > {marker}\n")
        os.chmod(chain, 0o755)
        payload = json.dumps(
            {
                "type": "agent-turn-complete",
                "last-assistant-message": "my earlier check was wrong",
            }
        )
        run_codex_notify([chain, payload])
        self.assertTrue(os.path.isfile(marker))


class TestCodexInstaller(unittest.TestCase):
    def test_compute_notify_update_prepends(self):
        from install_codex_notify import compute_notify_update

        text = 'notify = ["python3", "/home/x/.codex/hooks/diu-stop/codex_notify.py"]\n'
        new_text, changed, _ = compute_notify_update(
            text, "/home/x/.codex/hooks/wrong-check-reflect/codex_notify.py"
        )
        self.assertTrue(changed)
        self.assertIn("wrong-check-reflect/codex_notify.py", new_text)
        self.assertIn("diu-stop/codex_notify.py", new_text)
        # wrong-check comes first so it chains to diu-stop
        self.assertLess(
            new_text.index("wrong-check-reflect"),
            new_text.index("diu-stop"),
        )


if __name__ == "__main__":
    unittest.main()
