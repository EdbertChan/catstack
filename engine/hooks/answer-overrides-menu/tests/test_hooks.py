#!/usr/bin/env python3
"""Tests for the answer-overrides-menu PostToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/answer-overrides-menu/tests -v
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_posttooluse  # noqa: E402
import detect  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
OVERRIDE_FIXTURE = os.path.join(FIXTURES, "real_free_text_override.json")
MENU_PICK_FIXTURE = os.path.join(FIXTURES, "real_menu_pick.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def run_hook(payload) -> str:
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out):
            claude_posttooluse.main()
    return out.getvalue()


def menu_payload(labels, answer, multi_select=False) -> dict:
    question = "Which one?"
    spec = {
        "question": question,
        "header": "Pick",
        "multiSelect": multi_select,
        "options": [{"label": label, "description": ""} for label in labels],
    }
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [spec]},
        "tool_response": {"questions": [spec], "answers": {question: answer}},
    }


class TestFires(unittest.TestCase):
    def test_fires_on_real_free_text_answer_to_a_menu(self):
        payload = load(OVERRIDE_FIXTURE)
        found = detect.overrides(payload)
        answers = [answer for _, answer in found]
        self.assertIn("0DTE and futures. futures need to be checked", answers)
        self.assertNotIn(
            "New repo: EdbertChan/trend-reversal (Recommended)",
            answers,
            "an answer that is verbatim one of its own question's labels is a menu pick",
        )
        self.assertEqual(len(found), 2)

    def test_hook_emits_additional_context_quoting_the_override_verbatim(self):
        out = json.loads(run_hook(load(OVERRIDE_FIXTURE)))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("answer-overrides-menu:", context)
        self.assertIn("binding parameter", context)
        self.assertIn("0DTE and futures. futures need to be checked", context)

    def test_fires_when_a_label_is_answered_for_a_different_question(self):
        payload = load(OVERRIDE_FIXTURE)
        questions = payload["tool_response"]["questions"]
        borrowed = questions[0]["options"][0]["label"]
        payload["tool_response"]["answers"][questions[2]["question"]] = borrowed
        found = dict(detect.overrides(payload))
        self.assertEqual(found.get(questions[2]["question"]), borrowed)

    def test_fires_on_a_partial_multiselect_answer(self):
        payload = menu_payload(["Alpha", "Beta", "Gamma"], "Alpha, Delta", multi_select=True)
        self.assertEqual(len(detect.overrides(payload)), 1)

    def test_fires_on_a_nonempty_freeform_response_field(self):
        payload = menu_payload(["Alpha", "Beta"], "Alpha")
        payload["tool_response"]["response"] = "actually neither, use Gamma"
        found = detect.overrides(payload)
        self.assertEqual([answer for _, answer in found], ["actually neither, use Gamma"])


class TestStaysSilent(unittest.TestCase):
    def test_silent_on_a_real_menu_pick(self):
        payload = load(MENU_PICK_FIXTURE)
        self.assertEqual(detect.overrides(payload), [])
        self.assertIsNone(detect.decide(payload))
        self.assertEqual(run_hook(payload), "")

    def test_silent_when_every_real_answer_is_replaced_by_its_own_first_label(self):
        payload = load(OVERRIDE_FIXTURE)
        for question in payload["tool_response"]["questions"]:
            payload["tool_response"]["answers"][question["question"]] = question["options"][0]["label"]
        self.assertEqual(detect.overrides(payload), [])

    def test_silent_on_a_full_multiselect_answer(self):
        payload = menu_payload(["Alpha", "Beta", "Gamma"], "Alpha, Gamma", multi_select=True)
        self.assertEqual(detect.overrides(payload), [])

    def test_silent_on_surrounding_whitespace_and_an_empty_response_field(self):
        payload = menu_payload(["Alpha", "Beta"], "  Alpha  ")
        payload["tool_response"]["response"] = "   "
        self.assertEqual(detect.overrides(payload), [])

    def test_silent_for_a_subagent_turn(self):
        payload = load(OVERRIDE_FIXTURE)
        payload["agent_id"] = "sub-1"
        self.assertEqual(run_hook(payload), "")

    def test_silent_on_other_tools_and_on_an_unknown_question_key(self):
        other = copy.deepcopy(load(OVERRIDE_FIXTURE))
        other["tool_name"] = "Bash"
        self.assertEqual(detect.overrides(other), [])
        unknown = menu_payload(["Alpha", "Beta"], "Alpha")
        unknown["tool_response"]["answers"] = {"a question never asked": "anything at all"}
        self.assertEqual(detect.overrides(unknown), [])

    def test_fails_open_on_garbage_and_malformed_payloads(self):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stdout(out):
                claude_posttooluse.main()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(run_hook([1, 2, 3]), "")
        self.assertEqual(detect.overrides({}), [])
        self.assertEqual(detect.overrides({"tool_name": "AskUserQuestion"}), [])
        self.assertEqual(
            detect.overrides(
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {"questions": "not a list"},
                    "tool_response": {"answers": None},
                }
            ),
            [],
        )
        self.assertEqual(
            detect.overrides(
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {"questions": [{"question": "q", "options": [{"label": None}]}]},
                    "tool_response": {"answers": {"q": "typed"}},
                }
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
