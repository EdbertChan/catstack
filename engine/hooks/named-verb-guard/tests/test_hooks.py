#!/usr/bin/env python3
"""Tests for the named-verb-guard Stop hook.

Run: python3 -m unittest discover -s engine/hooks/named-verb-guard/tests -v

Fixture texts paraphrase real session shapes: "test and push" answered with a
bare "tests pass"; "prove it" asked seven times because rows carried no
citation; "stop" followed by more edits. Positive cases block, negative
cases stay silent.
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

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def transcript_with(user_texts, tool_uses_after_last=()):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for text in user_texts:
        tmp.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        tmp.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "working"}]}}) + "\n")
    for name, tool_input in tool_uses_after_last:
        tmp.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": name, "input": tool_input}]}}) + "\n")
    tmp.close()
    return tmp.name


def run_hook(transcript_path, assistant_message, stop_hook_active=False):
    payload = {
        "transcript_path": transcript_path,
        "last_assistant_message": assistant_message,
        "stop_hook_active": stop_hook_active,
    }
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


BARE_PASS = "Fixed the lot builder and re-ran the suite. All tests pass, pushed to the branch."
FENCED_PASS = (
    "Fixed the lot builder.\n\n```\n$ python3 -m pytest tests/test_lots.py -q\n"
    "12 passed in 0.41s\n```\n\nPushed as 3f2a9c1."
)


class TestBlocks(unittest.TestCase):
    def test_asked_to_test_bare_pass_claim_blocks(self):
        path = transcript_with(["help fix test and push"])
        try:
            blocked, err = run_hook(path, BARE_PASS)
            self.assertTrue(blocked)
            self.assertIn("named-verb-guard (test)", err)
        finally:
            os.unlink(path)

    def test_repro_request_answered_with_prose_blocks(self):
        path = transcript_with(["repro the missing SERV row first, then fix"])
        try:
            blocked, err = run_hook(path, "I reproduced it: the cost basis lookup returns None for SERV so the row is dropped. Fixing now.")
            self.assertTrue(blocked)
            self.assertIn("repro", err)
        finally:
            os.unlink(path)

    def test_prove_it_second_time_bare_assurance_blocks(self):
        path = transcript_with([
            "regenerate the sheet",
            "prove it. show me the output",
            "are you sure? the row still says 0",
        ])
        try:
            blocked, err = run_hook(path, "Yes, I'm sure. The regenerated sheet has the corrected row and the totals reconcile.")
            self.assertTrue(blocked)
            self.assertIn("more than once", err)
        finally:
            os.unlink(path)

    def test_delete_request_with_no_delete_command_blocks(self):
        path = transcript_with(["delete the duplicate 13F parser"], [("Read", {"file_path": "/x/parsers.py"})])
        try:
            blocked, err = run_hook(path, "Removed the duplicate parser; the module now has one 13F parser.")
            self.assertTrue(blocked)
            self.assertIn("delete", err)
        finally:
            os.unlink(path)

    def test_stop_followed_by_edits_this_turn_blocks(self):
        path = transcript_with(["STOP"], [("Edit", {"file_path": "/x/a.py"}), ("Bash", {"command": "pytest -q"})])
        try:
            blocked, err = run_hook(path, "Stopped. I made one last edit so the file compiles.")
            self.assertTrue(blocked)
            self.assertIn("stop means stop", err)
        finally:
            os.unlink(path)

    def test_show_me_request_with_no_link_or_output_blocks(self):
        path = transcript_with(["please regenerate and show me the portfolio going back to all time"])
        try:
            blocked, _ = run_hook(path, "Regenerated the portfolio tab with the full history. It is in the sheet now.")
            self.assertTrue(blocked)
        finally:
            os.unlink(path)


class TestStaysSilent(unittest.TestCase):
    def test_asked_to_test_fenced_pass_line_allows(self):
        path = transcript_with(["help fix test and push"])
        try:
            blocked, _ = run_hook(path, FENCED_PASS)
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_file_line_reference_counts_as_evidence_allows(self):
        path = transcript_with(["prove the lookback is 8 quarters"])
        try:
            blocked, _ = run_hook(path, "The lookback is set at pipeline/holdings.py:142 (`LOOKBACK_QUARTERS = 8`).")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_prove_it_first_time_is_silent(self):
        path = transcript_with(["regenerate the sheet", "are you sure the row is right?"])
        try:
            blocked, _ = run_hook(path, "Yes, the row matches the filing total.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_show_me_with_url_allows(self):
        path = transcript_with(["please regenerate and show me the portfolio going back to all time"])
        try:
            blocked, _ = run_hook(path, "Regenerated. Sheet: https://docs.google.com/spreadsheets/d/abc123")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_delete_request_with_rm_command_this_turn_allows(self):
        path = transcript_with(["delete the duplicate 13F parser"], [("Bash", {"command": "git rm pipeline/parsers/thirteen_f_dup.py"})])
        try:
            blocked, _ = run_hook(path, "Removed the duplicate parser; the module now has one 13F parser.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_stop_with_only_reads_allows(self):
        path = transcript_with(["stop"], [("Read", {"file_path": "/x/a.py"})])
        try:
            blocked, _ = run_hook(path, "Stopped. Nothing was changed after your message.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_calm_request_without_named_verb_is_silent(self):
        path = transcript_with(["why isnt the 72,000,000 transaction recorded in my sheet?"])
        try:
            blocked, _ = run_hook(path, "Because the 13F only reports quarter-end positions, the mid-quarter sale shows up next filing.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_verb_as_noun_does_not_fire(self):
        path = transcript_with(["the test is flaky on CI, what do you think is going on"])
        try:
            blocked, _ = run_hook(path, "It races on the shared temp dir. Two workers write the same fixture path.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_hook_feedback_line_is_not_the_users_message_silent(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        tmp.write(json.dumps({"type": "user", "message": {"role": "user", "content": "ok thats fine"}}) + "\n")
        tmp.write(json.dumps({"type": "user", "message": {"role": "user", "content":
            "Stop hook feedback: either show what was actually run/checked, or prefix the claim"}}) + "\n")
        tmp.close()
        try:
            blocked, _ = run_hook(tmp.name, "Noted, moving on to the next row.")
            self.assertFalse(blocked)
        finally:
            os.unlink(tmp.name)

    def test_unverified_prefix_allows(self):
        path = transcript_with(["run the regression suite"])
        try:
            blocked, _ = run_hook(path, "UNVERIFIED: the suite did not finish inside the sandbox timeout; rerun with a longer timeout.")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_clarifying_question_reply_allows(self):
        path = transcript_with(["run it"])
        try:
            blocked, _ = run_hook(path, "Which one: the export or the full pipeline?")
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_stop_hook_active_allows(self):
        path = transcript_with(["help fix test and push"])
        try:
            blocked, _ = run_hook(path, BARE_PASS, stop_hook_active=True)
            self.assertFalse(blocked)
        finally:
            os.unlink(path)

    def test_missing_transcript_fails_open(self):
        blocked, _ = run_hook("/nonexistent/transcript.jsonl", BARE_PASS)
        self.assertFalse(blocked)

    def test_garbage_stdin_prints_nothing(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


class TestDetectUnits(unittest.TestCase):
    def test_named_verbs_only_match_imperatives(self):
        self.assertEqual(detect.named_verbs("help fix test and push"), ["test"])
        self.assertEqual(detect.named_verbs("the test is flaky"), [])
        self.assertEqual(detect.named_verbs("STOP"), ["stop"])
        self.assertEqual(detect.named_verbs("stop the server before you migrate, then run migrations and keep going"), ["run"])


if __name__ == "__main__":
    unittest.main()
