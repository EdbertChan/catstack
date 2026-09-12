import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)
sys.path.insert(0, HOOK_DIR)

import plain_words
from testing import JudgeTestCase

REPLY = "No hook decides differently. Preflight passes and the review unit is engine-runtime."
ASKED = "Is it safe?"


def _transcript(folder, rows):
    path = os.path.join(folder, "chat.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _hit(job_id, closest, category="plain-words-made-up-labels"):
    return {"id": job_id, "hook": plain_words.HOOK_NAME, "outcome": "hit", "answer": {"match": True, "category": category, "closest": closest}}


class PlainWordsCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.judge, _ = plain_words._llm_judge()

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def payload(self, rows=(_user(ASKED), _assistant(REPLY)), **extra):
        payload = {"last_assistant_message": REPLY}
        if rows is not None:
            payload["transcript_path"] = _transcript(self.tmp, rows)
        payload.update(extra)
        return payload


class TestJob(PlainWordsCase):
    def test_one_job_names_every_word_list(self):
        built = plain_words.job(self.payload())
        self.assertEqual(built["hook"], plain_words.HOOK_NAME)
        self.assertEqual(built["hit_if_all_true"], ["match"])
        for name in plain_words.list_names():
            self.assertIn(name, built["prompt"])

    def test_the_job_carries_the_user_message_and_the_reply(self):
        built = plain_words.job(self.payload())
        self.assertIn(ASKED, built["prompt"])
        self.assertIn(REPLY, built["prompt"])
        self.assertIn("copied word for word from the ASSISTANT text", built["prompt"])

    def test_no_job_without_a_transcript_file(self):
        self.assertIsNone(plain_words.job({"last_assistant_message": REPLY}))
        self.assertIsNone(plain_words.job({"last_assistant_message": REPLY, "transcript_path": "/no/such/file.jsonl"}))

    def test_no_job_when_the_reply_is_empty(self):
        self.assertIsNone(plain_words.job(self.payload(last_assistant_message="   ")))


class TestMessage(PlainWordsCase):
    def test_a_hit_quoting_the_reply_becomes_a_message(self):
        text = plain_words.message_for(_hit("j1", "No hook decides differently."), REPLY)
        self.assertIn("No hook decides differently.", text)
        self.assertIn("plain-words-made-up-labels", text)

    def test_a_hit_quoting_the_word_list_is_dropped(self):
        self.assertEqual(plain_words.message_for(_hit("j1", "Force-push with lease, then a three-way apply."), REPLY), "")

    def test_a_clean_or_unchecked_verdict_says_nothing(self):
        for outcome in ("clean", "unchecked"):
            with self.subTest(outcome=outcome):
                self.assertEqual(plain_words.message_for({"id": "j1", "outcome": outcome}, REPLY), "")


class TestCheckReply(PlainWordsCase):
    def test_the_hit_comes_back_in_the_same_turn(self):
        payload = self.payload()
        built = {
            "id": "fixed",
            "hook": plain_words.HOOK_NAME,
            "transcript": payload["transcript_path"],
            "prompt": "p",
            "hit_if_all_true": ["match"],
            "on_hit": "o",
        }
        with patch.object(plain_words, "job", return_value=built):
            with patch.object(self.judge, "enqueue", return_value="fixed"):
                with patch.object(self.judge, "drain", return_value=[_hit("fixed", "No hook decides differently.")]):
                    text = plain_words.check_reply(payload)
        self.assertIn("No hook decides differently.", text)
        self.assertIn("plain-words-made-up-labels", text)

    def test_nothing_is_asked_for_a_rewrite_or_a_subagent(self):
        for extra in ({"stop_hook_active": True}, {"agent_id": "sub"}):
            with self.subTest(extra=extra):
                with patch.object(self.judge, "enqueue", side_effect=AssertionError("must not be called")):
                    self.assertEqual(plain_words.check_reply(self.payload(**extra)), "")

    def test_no_answer_in_time_ends_the_turn_unblocked(self):
        os.environ[plain_words.WAIT_ENV] = "0"
        try:
            with patch.object(self.judge, "enqueue", side_effect=lambda job: job["id"]):
                with patch.object(self.judge, "drain", return_value=[]):
                    self.assertEqual(plain_words.check_reply(self.payload()), "")
        finally:
            del os.environ[plain_words.WAIT_ENV]

    def test_a_failure_is_reported_and_not_raised(self):
        err = io.StringIO()
        with patch.object(self.judge, "enqueue", side_effect=OSError("disk full")):
            with redirect_stderr(err):
                self.assertEqual(plain_words.try_check_reply(self.payload()), "")
        self.assertIn("plain-words check failed", err.getvalue())
        self.assertIn("disk full", err.getvalue())


if __name__ == "__main__":
    unittest.main()
