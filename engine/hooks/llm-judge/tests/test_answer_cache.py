from __future__ import annotations

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import judge  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402


class TestAnswerCache(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.calls = os.path.join(self.state.name, "calls.log")
        script = (
            "import json, sys; open(sys.argv[1], 'a').write('x\\n'); "
            "print(json.dumps({'match': True}))"
        )
        self.use_runners(["counting", [sys.executable, "-c", script, self.calls, judge.PROMPT_SLOT]])

    def runner_calls(self) -> int:
        if not os.path.exists(self.calls):
            return 0
        with open(self.calls, encoding="utf-8") as handle:
            return len(handle.read().splitlines())

    def run_job(self, prompt: str, **extra) -> dict:
        job = {"id": f"job-{time.time_ns()}", "hook": "t", "transcript": "/t.jsonl", "prompt": prompt, "hit_if_all_true": ["match"], **extra}
        path = os.path.join(self.state.name, "jobs", f"{job['id']}.json")
        judge.write_json_atomic(path, job)
        return judge.run_job(path)

    def test_same_prompt_twice_calls_the_runner_once(self):
        first = self.run_job("does this ask to delete?")
        second = self.run_job("does this ask to delete?")
        self.assertEqual(self.runner_calls(), 1)
        self.assertEqual(first["outcome"], "hit")
        self.assertEqual(second["outcome"], "hit")
        self.assertEqual(second["attempts"][0]["runner"], "cache")

    def test_different_prompt_calls_the_runner_again(self):
        self.run_job("prompt one")
        self.run_job("prompt two")
        self.assertEqual(self.runner_calls(), 2)

    def test_answer_older_than_a_day_is_asked_again(self):
        self.run_job("stale prompt")
        path = judge.answer_cache_path("stale prompt")
        with open(path, encoding="utf-8") as handle:
            cached = json.load(handle)
        cached["at"] = time.time() - judge.ANSWER_CACHE_SECONDS - 1
        judge.write_json_atomic(path, cached)
        self.run_job("stale prompt")
        self.assertEqual(self.runner_calls(), 2)

    def test_investigate_jobs_are_never_reused(self):
        self.run_job("look at the repo", mode="investigate")
        self.run_job("look at the repo", mode="investigate")
        self.assertEqual(self.runner_calls(), 2)

    def test_changed_runner_set_asks_again(self):
        self.run_job("same words")
        other_calls = os.path.join(self.state.name, "other.log")
        script = "import json, sys; open(sys.argv[1], 'a').write('x\\n'); print(json.dumps({'match': False}))"
        self.use_runners(["other", [sys.executable, "-c", script, other_calls, judge.PROMPT_SLOT]])
        self.assertEqual(self.run_job("same words")["outcome"], "clean")

    def test_unchecked_result_is_not_remembered(self):
        self.use_runners(["broken", [sys.executable, "-c", "import sys; sys.exit(3)", judge.PROMPT_SLOT]])
        self.assertEqual(self.run_job("p")["outcome"], "unchecked")
        self.assertFalse(os.path.exists(judge.answer_cache_path("p")))

    def test_corrupt_cache_file_is_logged_and_asked_again(self):
        path = judge.answer_cache_path("corrupt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        self.assertEqual(self.run_job("corrupt")["outcome"], "hit")
        self.assertEqual(self.runner_calls(), 1)
        with open(os.path.join(self.state.name, "judge.log"), encoding="utf-8") as handle:
            self.assertIn("answer cache: could not read", handle.read())


if __name__ == "__main__":
    unittest.main()
