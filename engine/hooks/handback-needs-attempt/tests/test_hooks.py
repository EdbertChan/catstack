from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))

import claude_stop_check
import detect
import inbox
from judge_test_base import JudgeTestCase


PY = sys.executable
MATCH = json.dumps({"match": True, "closest": "Please run the command"})
CLEAN = json.dumps({"match": False, "closest": ""})
MATCH_RUNNER = ["match", [PY, "-c", f"print({MATCH!r})", "{prompt}"]]
CLEAN_RUNNER = ["clean", [PY, "-c", f"print({CLEAN!r})", "{prompt}"]]
MISSING_RUNNER = ["missing", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def write_transcript(directory, events):
    path = os.path.join(directory, "session.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return path


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.state_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "HANDBACK_NEEDS_ATTEMPT_STATE_DIR": self.state_dir.name,
        })
        self.env.start()
        detect.STATE_DIR = self.state_dir.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while os.path.isdir(os.path.join(self.state.name, "jobs")) and os.listdir(os.path.join(self.state.name, "jobs")) and time.monotonic() < deadline:
            time.sleep(0.05)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        self.env.stop()
        self.state_dir.cleanup()
        self.work.cleanup()
        super().tearDown()

    def wait_for_message(self, path):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            messages = inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.05)
        return []

    def enqueue_case(self, case, runner):
        self.use_runners(runner)
        path = write_transcript(self.work.name, case["events"])
        return path, detect.enqueue_judge({
            "last_assistant_message": case["reply"],
            "transcript_path": path,
        })

    def test_dictionary_loads(self):
        dictionary = detect._phrases().load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")
        self.assertEqual(dictionary["reads"], "exchange")

    def test_flagging_fixtures_queue_hits(self):
        for case in load("handbacks_fires.json"):
            with self.subTest(label=case["label"]):
                path, job_id = self.enqueue_case(case, MATCH_RUNNER)
                self.assertIsNotNone(job_id)
                self.assertTrue(any("handback-needs-attempt" in message for message in self.wait_for_message(path)))

    def test_permission_and_refusal_fixtures_stay_silent(self):
        for case in load("handbacks_silent.json")[:2]:
            with self.subTest(label=case["label"]):
                path, job_id = self.enqueue_case(case, CLEAN_RUNNER)
                self.assertIsNotNone(job_id)
                deadline = time.monotonic() + 10
                while os.path.isdir(os.path.join(self.state.name, "jobs")) and os.listdir(os.path.join(self.state.name, "jobs")) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(inbox.messages(path), [])

    def test_human_only_and_attempted_fixtures_stay_silent(self):
        for case in load("handbacks_silent.json")[2:]:
            with self.subTest(label=case["label"]):
                path, job_id = self.enqueue_case(case, CLEAN_RUNNER)
                self.assertIsNotNone(job_id)
                deadline = time.monotonic() + 10
                while os.path.isdir(os.path.join(self.state.name, "jobs")) and os.listdir(os.path.join(self.state.name, "jobs")) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(inbox.messages(path), [])

    def test_judge_failure_is_unchecked(self):
        case = load("handbacks_fires.json")[0]
        path, job_id = self.enqueue_case(case, MISSING_RUNNER)
        self.assertIsNotNone(job_id)
        message = self.wait_for_message(path)[0]
        self.assertIn("could not judge", message)
        self.assertIn("unchecked, not clean", message)

    def test_exchange_contains_reply_and_tool_records(self):
        case = load("handbacks_silent.json")[0]
        path, job_id = self.enqueue_case(case, CLEAN_RUNNER)
        self.assertIsNotNone(job_id)
        jobs = os.listdir(os.path.join(self.state.name, "jobs"))
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn(case["reply"], job["prompt"])
        self.assertIn("Permission denied by user", job["prompt"])

    def test_stop_hook_active_returns_without_queueing(self):
        case = load("handbacks_fires.json")[0]
        path = write_transcript(self.work.name, case["events"])
        self.assertIsNone(detect.enqueue_judge({
            "last_assistant_message": case["reply"],
            "transcript_path": path,
            "stop_hook_active": True,
        }))
        self.assertFalse(os.path.isdir(os.path.join(self.state.name, "jobs")))

    def test_same_reply_is_not_queued_again_within_ttl(self):
        case = load("handbacks_fires.json")[0]
        self.use_runners(MATCH_RUNNER)
        path = write_transcript(self.work.name, case["events"])
        payload = {"last_assistant_message": case["reply"], "transcript_path": path}
        self.assertIsNotNone(detect.enqueue_judge(payload))
        self.assertIsNone(detect.enqueue_judge(payload))

    def test_prompt_marker_expires_after_ttl(self):
        case = load("handbacks_fires.json")[0]
        path = write_transcript(self.work.name, case["events"])
        key = detect.reply_key(path, case["reply"])
        detect.mark_prompted(key)
        os.utime(detect._state_file(key), (time.time() - detect.STATE_TTL_SECONDS - 1,) * 2)
        self.assertFalse(detect.already_prompted(key))

    def test_unreadable_transcript_fails_open(self):
        case = load("handbacks_fires.json")[0]
        self.use_runners(MATCH_RUNNER)
        self.assertIsNone(detect.enqueue_judge({
            "last_assistant_message": case["reply"],
            "transcript_path": os.path.join(self.work.name, "missing.jsonl"),
        }))

    def test_claude_stop_reports_detector_errors(self):
        error = io.StringIO()
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("judge broke")):
            with patch.object(sys, "stdin", io.StringIO(json.dumps({}))), redirect_stderr(error):
                claude_stop_check.main()
        self.assertIn("handback-needs-attempt", error.getvalue())


if __name__ == "__main__":
    unittest.main()
