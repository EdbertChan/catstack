from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)
import detect
sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))
import judge
import phrases


class TestHandbackNeedsAttempt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.temp.name, "turn.jsonl")
        self.jobs = os.path.join(self.temp.name, "jobs")
        self.settings = {
            "CATSTACK_LLM_JUDGE_STATE_DIR": self.temp.name,
            "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.temp.name, "metrics"),
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows):
        with open(self.transcript, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def enqueue(self, reply, rows=()):
        self.write([
            {"type": "user", "message": {"role": "user", "content": "do it"}},
            *rows,
            {"type": "assistant", "message": {"role": "assistant", "content": reply}},
        ])
        with patch.dict(os.environ, self.settings, clear=False):
            return detect.enqueue_judge({"transcript_path": self.transcript})

    def test_command_handback_without_attempt_flags(self):
        job_id = self.enqueue("Please run: invoker-cli setup slack ... then tell me when it completes")
        self.assertIsNotNone(job_id)

    def test_step_handback_without_attempt_flags(self):
        job_id = self.enqueue("Simulator build still passes. Now on your end in Xcode:")
        self.assertIsNotNone(job_id)

    def test_permission_denial_is_in_exchange(self):
        job_id = self.enqueue(
            "Please run the command yourself.",
            [{"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "permission denied by sandbox"}
            ]}, "toolUseResult": {"is_error": True}},],
        )
        self.assertIsNotNone(job_id)
        with open(os.path.join(self.temp.name, "jobs", f"{job_id}.json"), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn("permission denied", job["prompt"])

    def test_oauth_consent_is_in_exchange(self):
        job_id = self.enqueue(
            "Please approve the OAuth consent in your browser.",
            [{"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "OAuth consent required from the human"}
            ]}, "toolUseResult": {"is_error": True}},],
        )
        self.assertIsNotNone(job_id)
        with open(os.path.join(self.temp.name, "jobs", f"{job_id}.json"), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn("OAuth consent", job["prompt"])

    def test_judge_failure_is_unchecked(self):
        job_id = self.enqueue("Please run the setup command and tell me when it completes")
        self.assertIsNotNone(job_id)
        dictionary = phrases.load("handback-needs-attempt")
        result = judge.verdict(
            phrases.job(dictionary, self.transcript, "Please run the setup command and tell me when it completes"),
            {"outcome": "unchecked", "attempts": [{"runner": "fake", "reason": "failed"}]},
        )
        self.assertEqual(result["outcome"], "unchecked")

    def test_permission_denial_is_silent_verdict(self):
        dictionary = phrases.load("handback-needs-attempt")
        result = judge.verdict(
            phrases.job(dictionary, self.transcript, "The sandbox denied the command."),
            {"outcome": "answered", "runner": "fake", "answer": {"match": False}},
        )
        self.assertEqual(result["outcome"], "clean")

    def test_oauth_consent_is_silent_verdict(self):
        dictionary = phrases.load("handback-needs-attempt")
        result = judge.verdict(
            phrases.job(dictionary, self.transcript, "OAuth consent is required in your browser."),
            {"outcome": "answered", "runner": "fake", "answer": {"match": False}},
        )
        self.assertEqual(result["outcome"], "clean")

    def test_stop_hook_active_is_silent(self):
        self.write([{ "type": "assistant", "message": {"role": "assistant", "content": "Please run it"}}])
        with patch.dict(os.environ, self.settings, clear=False):
            self.assertIsNone(detect.enqueue_judge({"transcript_path": self.transcript, "stop_hook_active": True}))


if __name__ == "__main__":
    unittest.main()
