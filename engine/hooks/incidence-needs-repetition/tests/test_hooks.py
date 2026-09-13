#!/usr/bin/env python3
"""Tests for incidence-needs-repetition."""
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
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import judge  # noqa: E402
import phrases  # noqa: E402

PY = sys.executable
HIT_TEXT = "The test passes on every attempt now; it never fails anymore."
CLEAN_TEXT = "I ran it once and it passed."
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": HIT_TEXT})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
SLOW_CLEAN = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


def assistant_bash(command: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}]},
    })


class TestIncidenceNeedsRepetition(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.work = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            judge.STATE_ENV: self.state.name,
            judge.RUNNERS_ENV: json.dumps([ANSWERS_HIT]),
        })
        self.env.start()
        os.environ.pop(judge.CHILD_ENV, None)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.env.stop()
        self.state.cleanup()
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, *lines: tuple[str, str], name: str = "session.jsonl") -> str:
        path = os.path.join(self.work.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for role, text in lines:
                handle.write(transcript_line(role, text) + "\n")
        return path

    def wait_for_jobs(self, count: int, seconds: float = 5) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                return jobs
            time.sleep(0.05)
        return self.jobs()

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            got = judge_inbox.messages(path)
            if got:
                return got
            time.sleep(0.1)
        return []

    def test_dictionary_loads(self):
        dictionary = phrases.load("incidence-needs-repetition")
        self.assertEqual(dictionary["checker"], "incidence-needs-repetition")
        self.assertIn("claims behaviour across runs", dictionary["on_hit"])

    def test_decide_no_longer_returns_pattern_hit(self):
        self.assertIsNone(detect.decide({"last_assistant_message": HIT_TEXT}))
        self.assertIsNone(detect.decide_from_lines(HIT_TEXT, []))

    def test_job_is_queued_for_an_ordinary_reply(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([SLOW_CLEAN])
        path = self.write_transcript(("assistant", CLEAN_TEXT))
        job_id = detect.enqueue_judge({"transcript_path": path})
        self.assertIsNotNone(job_id)
        jobs = self.wait_for_jobs(1)
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            job = json.load(handle)
        self.assertEqual(job["hook"], "incidence-needs-repetition")
        self.assertEqual(job["transcript"], path)
        self.assertEqual(job["on_hit"], phrases.load("incidence-needs-repetition")["on_hit"])

    def test_hit_verdict_reaches_agent_as_dictionary_on_hit_text(self):
        path = self.write_transcript(("assistant", HIT_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        dictionary = phrases.load("incidence-needs-repetition")
        self.assertEqual(self.wait_for_messages(path), [dictionary["on_hit"]])

    def test_clean_verdict_says_nothing(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([ANSWERS_CLEAN])
        path = self.write_transcript(("assistant", CLEAN_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_unchecked_verdict_says_could_not_judge(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([MISSING])
        path = self.write_transcript(("assistant", CLEAN_TEXT))
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_turn_exempted_by_twice_run_command_queues_nothing(self):
        path = self.write_transcript(
            ("user", "check it"),
            ("assistant", ""),
            ("assistant", ""),
            name="repeated.jsonl",
        )
        with open(path, "a", encoding="utf-8") as handle:
            handle.seek(0, 2)
            handle.write(assistant_bash("node repro.mjs") + "\n")
            handle.write(assistant_bash("node repro.mjs") + "\n")
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "last_assistant_message": HIT_TEXT}))
        self.assertEqual(self.jobs(), [])

    def test_stop_hook_active_queues_nothing(self):
        with patch.object(claude_stop_check, "try_enqueue_judge") as enqueue:
            with patch.object(sys, "stdin", io.StringIO(json.dumps({"stop_hook_active": True}))):
                claude_stop_check.main()
        enqueue.assert_called_once_with({"stop_hook_active": True})

    def test_missing_transcript_fails_open(self):
        self.assertIsNone(detect.enqueue_judge({
            "last_assistant_message": HIT_TEXT,
            "transcript_path": "/nonexistent/x.jsonl",
        }))
        self.assertEqual(self.jobs(), [])

    def test_judge_enqueue_error_fails_open(self):
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("state unavailable")):
            with patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                detect.try_enqueue_judge({"last_assistant_message": HIT_TEXT})
        self.assertIn("state unavailable", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
