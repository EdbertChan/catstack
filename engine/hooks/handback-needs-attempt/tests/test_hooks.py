import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import detect


def transcript(rows):
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for row in rows:
        handle.write(json.dumps(row) + "\n")
    handle.close()
    return handle.name


class FakeJudge:
    def __init__(self, result="job-id"):
        self.jobs = []
        self.result = result

    def enqueue(self, job):
        self.jobs.append(job)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class HookTests(unittest.TestCase):
    def setUp(self):
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def run_case(self, reply, rows=None):
        path = transcript(rows or [{"type": "user", "message": {"role": "user", "content": "do it"}}])
        payload = {"transcript_path": path, "last_assistant_message": reply}
        return path, payload

    def test_no_attempt_handback_flags_for_judging(self):
        path, payload = self.run_case("Please run: invoker-cli setup slack ... then tell me when it completes")
        judge = FakeJudge()
        with mock.patch.object(detect, "_judge", return_value=judge):
            self.assertEqual(detect.enqueue_judge(payload), "job-id")
        self.assertEqual(judge.jobs[0]["transcript"], path)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(judge.jobs[0]["tool_calls_and_results"], [json.loads(line) for line in handle])

    def test_xcode_handback_flags_for_judging(self):
        _, payload = self.run_case("Simulator build still passes. Now on your end in Xcode:")
        judge = FakeJudge()
        with mock.patch.object(detect, "_judge", return_value=judge):
            detect.enqueue_judge(payload)
        self.assertEqual(len(judge.jobs), 1)

    def test_permission_denial_handback_is_silent_candidate_context(self):
        rows = [
            {"type": "user", "message": {"role": "user", "content": "do it"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "setup"}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "is_error": True, "content": "Permission denied"}]}},
        ]
        _, payload = self.run_case("Please run setup yourself.", rows)
        judge = FakeJudge()
        with mock.patch.object(detect, "_judge", return_value=judge):
            detect.enqueue_judge(payload)
        self.assertIn("Permission denied", json.dumps(judge.jobs[0]["exchange"]))

    def test_oauth_consent_handback_is_silent_candidate_context(self):
        rows = [{"type": "user", "message": {"role": "user", "content": "OAuth consent is required"}}]
        _, payload = self.run_case("Please approve OAuth consent in your browser.", rows)
        judge = FakeJudge()
        with mock.patch.object(detect, "_judge", return_value=judge):
            detect.enqueue_judge(payload)
        self.assertEqual(len(judge.jobs), 1)

    def test_judge_failure_is_unchecked(self):
        _, payload = self.run_case("Please run setup yourself.")
        with mock.patch.object(detect, "_judge", return_value=FakeJudge(RuntimeError("down"))):
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                detect.try_enqueue_judge(payload)
        self.assertIn("unchecked", output.getvalue())

    def test_stop_hook_active_skips(self):
        _, payload = self.run_case("Please run setup yourself.")
        payload["stop_hook_active"] = True
        with mock.patch.object(detect, "_judge", return_value=FakeJudge()) as factory:
            self.assertIsNone(detect.enqueue_judge(payload))
            factory.assert_not_called()

    def test_unreadable_transcript_is_unchecked(self):
        payload = {"transcript_path": "/missing/handback.jsonl", "last_assistant_message": "Please run setup"}
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            detect.try_enqueue_judge(payload)
        self.assertIn("unchecked", output.getvalue())


if __name__ == "__main__":
    unittest.main()
