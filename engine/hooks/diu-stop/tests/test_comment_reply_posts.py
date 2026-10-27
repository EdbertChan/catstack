#!/usr/bin/env python3
"""Comment replies always post: a long one posts trimmed, and a refused thread's next try posts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, HOOK_DIR)

import comment_reply  # noqa: E402
import diu_limit  # noqa: E402

ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse_comment.py")
URL = "https://claude.ai/artifact/abc123"
LONG_PLAIN_REPLY = (
    "Done. Each step's critical path now opens into a full-width timeline like box 4 on the simulation page. "
    "Every job on the chain gets one row with its full name, a grey bar while it waits for a machine, and a blue bar while it runs. "
    "A red line marks where the chain ends after the step, and a dashed line marks where it ended one step before, so you can see what moved."
)
JARGON_REPLY = "Mostly regex false positives."


def reply_event(text: str, thread: str = "thread-1") -> dict:
    return {"tool_name": "ArtifactComments", "hook_event_name": "PreToolUse",
            "tool_input": {"action": "reply", "url": URL, "thread_id": thread, "text": text}}


def run_entrypoint(event: dict, state_path: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("CATSTACK_HOOK_MODE_DIU_STOP", None)
    env["CATSTACK_DIU_COMMENT_STATE"] = state_path
    with tempfile.TemporaryDirectory() as metrics:
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics
        return subprocess.run([sys.executable, ENTRYPOINT], input=json.dumps(event), capture_output=True, text=True, timeout=15, env=env)


class StateFile(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state = os.path.join(self.folder.name, "comment-refusals.json")
        os.environ["CATSTACK_DIU_COMMENT_STATE"] = self.state
        self.addCleanup(os.environ.pop, "CATSTACK_DIU_COMMENT_STATE", None)


class LongReplyPostsTrimmed(StateFile):
    def test_a_long_plain_reply_is_posted_trimmed_to_the_word_limit_instead_of_refused(self):
        result = run_entrypoint(reply_event(LONG_PLAIN_REPLY), self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        posted = json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]
        self.assertTrue(LONG_PLAIN_REPLY.startswith(posted["text"].rstrip(".…")[:40]), posted["text"])
        self.assertLessEqual(diu_limit.comment_words(posted["text"]), diu_limit.COMMENT_WORD_LIMIT)
        self.assertEqual((posted["url"], posted["thread_id"], posted["action"]), (URL, "thread-1", "reply"))

    def test_the_trimmed_reply_keeps_whole_sentences_from_the_start(self):
        trimmed = comment_reply.trim_to_limit(LONG_PLAIN_REPLY)
        self.assertEqual(trimmed, "Done. Each step's critical path now opens into a full-width timeline like box 4 on the simulation page.")

    def test_one_sentence_over_the_word_limit_is_cut_to_the_word_limit(self):
        trimmed = comment_reply.trim_to_limit(" ".join(["word"] * 70))
        self.assertLessEqual(diu_limit.comment_words(trimmed), diu_limit.COMMENT_WORD_LIMIT)
        self.assertTrue(trimmed.endswith("…"))


class RefusedThreadPostsTheNextTry(StateFile):
    def test_jargon_is_refused_once_then_the_next_try_on_that_thread_posts(self):
        first = run_entrypoint(reply_event(JARGON_REPLY), self.state)
        self.assertEqual(first.returncode, 2, first.stdout)
        second = run_entrypoint(reply_event(JARGON_REPLY), self.state)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["hookSpecificOutput"]["updatedInput"]["text"], JARGON_REPLY)

    def test_a_refusal_on_one_thread_does_not_pass_another_thread(self):
        self.assertEqual(run_entrypoint(reply_event(JARGON_REPLY, "thread-1"), self.state).returncode, 2)
        self.assertEqual(run_entrypoint(reply_event(JARGON_REPLY, "thread-2"), self.state).returncode, 2)

    def test_a_long_reply_with_jargon_posts_trimmed_on_the_second_try(self):
        text = LONG_PLAIN_REPLY + " The regex was the cause."
        self.assertEqual(run_entrypoint(reply_event(text), self.state).returncode, 2)
        second = run_entrypoint(reply_event(text), self.state)
        self.assertEqual(second.returncode, 0, second.stderr)
        posted = json.loads(second.stdout)["hookSpecificOutput"]["updatedInput"]["text"]
        self.assertLessEqual(diu_limit.comment_words(posted), diu_limit.COMMENT_WORD_LIMIT)

    def test_a_short_plain_reply_posts_unchanged_with_nothing_written(self):
        result = run_entrypoint(reply_event("Done. The timeline now shows each job."), self.state)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, ""))
        self.assertFalse(os.path.exists(self.state))


if __name__ == "__main__":
    unittest.main()
