#!/usr/bin/env python3
"""A comment reply that is too long or in jargon is posted rewritten by the judge's model; a bad or missing rewrite keeps the reminder.

Run: python3 -m unittest discover -s engine/hooks/diu-stop/tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "_sdk"))

import comment_reply  # noqa: E402
import comment_rewrite  # noqa: E402
import render  # noqa: E402

ARTIFACT_URL = "https://claude.ai/artifact/abc123"
LONG_REPLY = " ".join(["word"] * 70)
PLAIN_REWRITE = "Done. The second page now keeps the first page's fix."


def reply_event(text: str) -> dict:
    return {"tool_name": "ArtifactComments", "tool_input": {"action": "reply", "url": ARTIFACT_URL, "thread_id": "t1", "text": text}}


class TestRewrite(unittest.TestCase):
    def setUp(self):
        patched = mock.patch.dict(os.environ, {comment_rewrite.SWITCH_ENV: "on"})
        patched.start()
        self.addCleanup(patched.stop)

    def test_a_long_reply_is_posted_as_the_models_plain_rewrite(self):
        with mock.patch.object(comment_reply, "rewrite_reply", return_value=PLAIN_REWRITE) as model:
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_REWRITTEN])
        self.assertEqual(findings[0].output["updatedInput"]["text"], PLAIN_REWRITE)
        self.assertEqual(findings[0].output["updatedInput"]["thread_id"], "t1")
        model.assert_called_once()

    def test_the_rendered_claude_output_carries_the_rewritten_input(self):
        with mock.patch.object(comment_reply, "rewrite_reply", return_value=PLAIN_REWRITE):
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        stdout, _, code = render._render_claude("PreToolUse", "warn", findings[0].message, findings)
        self.assertEqual(code, 0)
        self.assertIn(PLAIN_REWRITE, stdout)
        self.assertIn("updatedInput", stdout)

    def test_a_rewrite_that_is_still_too_long_keeps_the_original_reminder(self):
        with mock.patch.object(comment_reply, "rewrite_reply", return_value=LONG_REPLY):
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_LENGTH])

    def test_a_rewrite_that_still_has_jargon_keeps_the_original_reminder(self):
        with mock.patch.object(comment_reply, "rewrite_reply", return_value="Mostly regex false positives."):
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_LENGTH])

    def test_no_model_answer_keeps_the_original_reminder(self):
        with mock.patch.object(comment_reply, "rewrite_reply", return_value=None):
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_LENGTH])

    def test_a_clean_short_reply_never_asks_the_model(self):
        with mock.patch.object(comment_reply, "rewrite_reply") as model:
            findings = comment_reply.detect(reply_event(PLAIN_REWRITE))
        self.assertEqual(findings, [])
        model.assert_not_called()

    def test_the_switch_turns_the_model_off(self):
        with mock.patch.dict(os.environ, {comment_rewrite.SWITCH_ENV: "off"}), mock.patch.object(comment_reply, "rewrite_reply") as model:
            findings = comment_reply.detect(reply_event(LONG_REPLY))
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_LENGTH])
        model.assert_not_called()

    def test_a_docs_utterance_is_never_rewritten(self):
        event = {"tool_name": "mcp__claude_ai_Claude_Docs__create",
                 "tool_input": {"object": "utterance", "payload": {"value": {"body": LONG_REPLY}}}}
        with mock.patch.object(comment_reply, "rewrite_reply") as model:
            findings = comment_reply.detect(event)
        self.assertEqual([finding.rule_id for finding in findings], [comment_reply.RULE_LENGTH])
        model.assert_not_called()


class TestRewriteReply(unittest.TestCase):
    def fake_judge(self, result: dict):
        judge = mock.Mock()
        judge.ask.return_value = result
        return mock.patch.object(comment_rewrite, "llm_judge", return_value=(judge, None)), judge

    def test_reads_the_reply_out_of_the_models_json_answer(self):
        patch, judge = self.fake_judge({"outcome": "answered", "answer": {"reply": f" {PLAIN_REWRITE} "}})
        with patch:
            self.assertEqual(comment_rewrite.rewrite_reply(LONG_REPLY, 40), PLAIN_REWRITE)
        self.assertEqual(judge.ask.call_args.kwargs["timeout_seconds"], comment_rewrite.RUNNER_TIMEOUT_SECONDS)

    def test_an_unanswered_job_is_none_and_says_why_on_stderr(self):
        patch, _ = self.fake_judge({"outcome": "unchecked", "answer": None, "attempts": [{"runner": "claude", "reason": "timed out"}]})
        with patch, mock.patch.object(sys, "stderr") as stderr:
            self.assertIsNone(comment_rewrite.rewrite_reply(LONG_REPLY, 40))
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("claude: timed out", written)


if __name__ == "__main__":
    unittest.main()
