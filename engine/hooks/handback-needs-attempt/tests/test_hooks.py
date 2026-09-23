from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, LLM_JUDGE_DIR)

import claude_stop_check
import detect
import inbox as judge_inbox
from judge_test_base import JudgeTestCase
import phrases


PYTHON = sys.executable
ANSWERS_HIT = ["fake", [PYTHON, "-c", "print('{\"match\": true}')", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PYTHON, "-c", "print('{\"match\": false}')", "{prompt}"]]
SLOW_CLEAN = ["slow", [PYTHON, "-c", "import time; time.sleep(2); print('{\"match\": false}')", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def load_fixtures():
    with open(os.path.join(FIXTURES, "handbacks.json"), encoding="utf-8") as handle:
        return json.load(handle)


def transcript_lines(turn):
    rows = []
    for item in turn:
        role = item["role"]
        if role == "user":
            rows.append({"type": "user", "message": {"role": "user", "content": item["text"]}})
        elif role == "assistant_tool":
            rows.append({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": item["name"], "input": item["input"]}
            ]}})
        else:
            rows.append({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": item["text"]}
            ]}, "toolUseResult": {"stdout": item["text"]}})
    return rows


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        warnings.simplefilter("ignore", ResourceWarning)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self):
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, case):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        for row in transcript_lines(case["turn"]):
            handle.write(json.dumps(row) + "\n")
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def wait_for_messages(self, path):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            messages = judge_inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.1)
        return []

    def wait_for_jobs(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                return jobs
            time.sleep(0.05)
        return self.jobs()

    def enqueue(self, case):
        path = self.write_transcript(case)
        job_id = detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": case["reply"],
        })
        self.assertIsNotNone(job_id)
        return path

    def test_dictionary_loads(self):
        dictionary = phrases.load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")
        self.assertEqual(dictionary["reads"], "exchange")

    def test_fires_for_required_handback_fixtures(self):
        self.use_runners(ANSWERS_HIT)
        for case in load_fixtures()["fires"]:
            with self.subTest(label=case["label"]):
                path = self.enqueue(case)
                self.assertTrue(self.wait_for_messages(path))

    def test_silent_after_permission_denial(self):
        self.use_runners(ANSWERS_CLEAN)
        case = load_fixtures()["silent"][0]
        path = self.enqueue(case)
        time.sleep(1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_silent_for_oauth_consent(self):
        self.use_runners(ANSWERS_CLEAN)
        case = load_fixtures()["silent"][1]
        path = self.enqueue(case)
        time.sleep(1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_silent_after_successful_attempt(self):
        self.use_runners(ANSWERS_CLEAN)
        case = load_fixtures()["silent"][2]
        path = self.enqueue(case)
        time.sleep(1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_judge_failure_is_unchecked(self):
        self.use_runners(MISSING)
        path = self.enqueue(load_fixtures()["fires"][0])
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_job_contains_reply_and_turn_exchange(self):
        self.use_runners(SLOW_CLEAN)
        case = load_fixtures()["silent"][0]
        path = self.enqueue(case)
        jobs = self.wait_for_jobs(1)
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertIn(case["reply"], job["prompt"])
        self.assertIn("invoker-cli setup slack", job["prompt"])
        self.assertIn("Permission denied by policy", job["prompt"])
        self.assertEqual(job["transcript"], path)

    def test_stop_hook_active_is_silent(self):
        case = load_fixtures()["fires"][0]
        path = self.write_transcript(case)
        self.assertIsNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": case["reply"],
            "stop_hook_active": True,
        }))
        self.assertEqual(self.jobs(), [])

    def test_unreadable_transcript_fails_open_as_unchecked(self):
        self.use_runners(ANSWERS_HIT)
        err = io.StringIO()
        with redirect_stderr(err):
            result = detect.enqueue_judge({
                "transcript_path": "/no/such/handback-session.jsonl",
                "last_assistant_message": load_fixtures()["fires"][0]["reply"],
            })
        self.assertIsNone(result)
        self.assertIn("unchecked", err.getvalue())

    def test_claude_stop_entrypoint_only_enqueues(self):
        self.use_runners(SLOW_CLEAN)
        case = load_fixtures()["fires"][0]
        path = self.write_transcript(case)
        with patch.object(sys, "stdin", io.StringIO(json.dumps({
            "transcript_path": path,
            "last_assistant_message": case["reply"],
        }))):
            with redirect_stderr(io.StringIO()):
                claude_stop_check.main()
        self.assertEqual(len(self.wait_for_jobs(1)), 1)


if __name__ == "__main__":
    unittest.main()
