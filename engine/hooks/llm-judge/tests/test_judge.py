#!/usr/bin/env python3
"""Unit tests for the backgrounded LLM judge.

Run: python3 -m unittest discover -s engine/hooks/llm-judge/tests -v
"""
import json
import os
import sys
import time
import unittest
import warnings
from unittest.mock import patch

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import judge  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable


def runner(name, script):
    return [name, [PY, "-c", script, "{prompt}"]]


ANSWER_MATCH = runner("answers", "import json, sys; print('thinking...'); print(json.dumps({'match': True, 'prompt': sys.argv[1]}))")
EXIT_NONZERO = runner("crashes", "import sys; sys.stderr.write('model quota exhausted'); sys.exit(3)")
PROSE_ONLY = runner("rambles", "print('I think the answer is yes')")
MISSING_BINARY = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]
SLOW_MATCH = runner("slow", "import json, sys, time; time.sleep(2); print(json.dumps({'match': True, 'prompt': sys.argv[1]}))")


class JudgeBehaviorTestCase(JudgeTestCase):
    def job(self, **overrides):
        base = {
            "id": "job-1",
            "hook": "demo-hook",
            "transcript": "/tmp/transcript-a.jsonl",
            "prompt": "is this a retraction?",
            "hit_if_all_true": ["match"],
            "on_hit": "demo-hook: the model says this matches",
        }
        base.update(overrides)
        return base


class TestAsk(JudgeBehaviorTestCase):
    def test_first_runner_fails_second_answers_and_one_failed_attempt_is_recorded(self):
        self.use_runners(EXIT_NONZERO, ANSWER_MATCH)
        result = judge.ask("hello judge")
        self.assertEqual(result["outcome"], "answered")
        self.assertEqual(result["runner"], "answers")
        self.assertEqual(result["answer"], {"match": True, "prompt": "hello judge"})
        failed = [a for a in result["attempts"] if not a["ok"]]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["runner"], "crashes")
        self.assertIn("model quota exhausted", failed[0]["reason"])
        self.assertEqual([a["runner"] for a in result["attempts"]], ["crashes", "answers"])

    def test_every_runner_fails_is_unchecked_with_one_attempt_per_runner(self):
        self.use_runners(EXIT_NONZERO, PROSE_ONLY)
        result = judge.ask("hello judge")
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIsNone(result["runner"])
        self.assertIsNone(result["answer"])
        self.assertEqual([a["runner"] for a in result["attempts"]], ["crashes", "rambles"])
        self.assertTrue(all(not a["ok"] for a in result["attempts"]))
        self.assertIn("no JSON object line", result["attempts"][1]["reason"])

    def test_missing_binary_is_recorded_as_not_installed(self):
        self.use_runners(MISSING_BINARY, ANSWER_MATCH)
        result = judge.ask("hello judge")
        self.assertEqual(result["attempts"][0], {"runner": "ghost", "ok": False, "reason": "not installed"})
        self.assertEqual(result["runner"], "answers")

    def test_last_json_object_line_wins(self):
        self.use_runners(runner("two", "print('{\"match\": false}'); print('[1, 2]'); print('{\"match\": true}')"))
        self.assertEqual(judge.ask("x")["answer"], {"match": True})

    def test_timed_out_runner_is_a_failed_attempt_and_next_runner_answers(self):
        self.use_runners(runner("hangs", "import time; time.sleep(30)"), ANSWER_MATCH)
        started = time.monotonic()
        with patch.object(judge, "TIMEOUT_SECONDS", 1):
            result = judge.ask("x")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(result["attempts"][0]["runner"], "hangs")
        self.assertFalse(result["attempts"][0]["ok"])
        self.assertIn("timed out after 1s", result["attempts"][0]["reason"])
        self.assertEqual(result["runner"], "answers")

    def test_runner_sees_child_env_and_a_fresh_temp_cwd(self):
        self.use_runners(runner("env", "import json, os; print(json.dumps({'child': os.environ.get('CATSTACK_LLM_JUDGE_CHILD'), 'cwd': os.getcwd()}))"))
        answer = judge.ask("x")["answer"]
        self.assertEqual(answer["child"], "1")
        self.assertNotEqual(os.path.realpath(answer["cwd"]), os.path.realpath(os.getcwd()))
        self.assertFalse(os.path.exists(answer["cwd"]))

    def test_long_stderr_reason_is_capped_at_300_characters(self):
        self.use_runners(runner("loud", "import sys; sys.stderr.write('e' * 5000); sys.exit(1)"))
        reason = judge.ask("x")["attempts"][0]["reason"]
        self.assertLessEqual(len(reason), 300)
        self.assertTrue(reason.startswith("exit 1: eee"))

    def test_malformed_runners_env_refuses_instead_of_running_defaults(self):
        os.environ[judge.RUNNERS_ENV] = "not json"
        with self.assertRaises(ValueError):
            judge.ask("x")

    def test_default_runner_order_is_codex_then_claude_then_cursor(self):
        self.assertEqual([name for name, _ in judge.runners()], ["codex", "claude", "cursor"])


class TestVerdict(JudgeBehaviorTestCase):
    def test_hit_when_every_hit_key_is_true(self):
        job = self.job(hit_if_all_true=["match", "sure"])
        result = judge.verdict(job, {"outcome": "answered", "runner": "answers", "answer": {"match": True, "sure": True}, "attempts": []})
        self.assertEqual(result["outcome"], "hit")
        self.assertEqual(result["on_hit"], job["on_hit"])
        self.assertEqual(result["runner"], "answers")

    def test_clean_when_one_hit_key_is_false_missing_or_not_a_real_boolean(self):
        job = self.job(hit_if_all_true=["match", "sure"])
        for answer in ({"match": True, "sure": False}, {"match": True}, {"match": True, "sure": "true"}):
            result = judge.verdict(job, {"outcome": "answered", "runner": "answers", "answer": answer, "attempts": []})
            self.assertEqual(result["outcome"], "clean", answer)
            self.assertIn("sure", result["reason"])

    def test_unchecked_when_ask_was_unchecked(self):
        attempts = [{"runner": "ghost", "ok": False, "reason": "not installed"}]
        result = judge.verdict(self.job(), {"outcome": "unchecked", "runner": None, "answer": None, "attempts": attempts})
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIn("ghost: not installed", result["reason"])
        self.assertEqual(result["attempts"], attempts)


class TestBackground(JudgeBehaviorTestCase):
    def test_enqueue_as_judge_child_returns_none_and_starts_nothing(self):
        os.environ[judge.CHILD_ENV] = "1"
        self.use_runners(ANSWER_MATCH)
        with patch.object(judge.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")) as popen:
            self.assertIsNone(judge.enqueue(self.job()))
        popen.assert_not_called()
        self.assertEqual(os.listdir(self.state.name), [])

    def test_enqueue_returns_before_slow_runner_and_drain_later_returns_hit(self):
        self.use_runners(SLOW_MATCH)
        job = self.job(id="slow-job")
        started = time.monotonic()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            job_id = judge.enqueue(job)
        elapsed = time.monotonic() - started
        self.assertEqual(job_id, "slow-job")
        self.assertLess(elapsed, 1.5)
        self.assertEqual(judge.drain(job["transcript"]), [])
        verdicts = []
        deadline = time.monotonic() + 15
        while not verdicts and time.monotonic() < deadline:
            time.sleep(0.2)
            verdicts = judge.drain(job["transcript"])
        self.assertEqual(len(verdicts), 1, "no verdict within 15 seconds")
        self.assertEqual(verdicts[0]["outcome"], "hit")
        self.assertEqual(verdicts[0]["id"], "slow-job")
        self.assertEqual(verdicts[0]["answer"]["prompt"], job["prompt"])
        self.assertFalse(os.path.exists(os.path.join(self.state.name, "jobs", "slow-job.json")))
        self.assertEqual(judge.drain(job["transcript"]), [])

    def test_run_job_writes_verdict_under_transcript_hash_and_deletes_job(self):
        self.use_runners(ANSWER_MATCH)
        path = os.path.join(self.state.name, "jobs", "job-1.json")
        judge.write_json_atomic(path, self.job())
        judge.run_job(path)
        self.assertFalse(os.path.exists(path))
        written = os.path.join(judge.verdict_dir("/tmp/transcript-a.jsonl"), "job-1.json")
        self.assertEqual(len(os.path.basename(os.path.dirname(written))), 16)
        with open(written, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["outcome"], "hit")

    def test_run_job_error_is_logged_and_still_writes_unchecked_verdict(self):
        os.environ[judge.RUNNERS_ENV] = "not json"
        path = os.path.join(self.state.name, "jobs", "broken-job.json")
        judge.write_json_atomic(path, self.job(id="broken-job"))
        judge.run_job(path)
        verdicts = judge.drain("/tmp/transcript-a.jsonl")
        self.assertEqual([v["outcome"] for v in verdicts], ["unchecked"])
        self.assertIn(judge.RUNNERS_ENV, verdicts[0]["reason"])
        with open(os.path.join(self.state.name, "judge.log"), encoding="utf-8") as handle:
            self.assertIn("job broken-job failed", handle.read())
        self.assertFalse(os.path.exists(path))

    def test_drain_returns_oldest_first_only_for_its_transcript_and_deletes_them(self):
        folder = judge.verdict_dir("/tmp/transcript-a.jsonl")
        for name, age in (("newer", 90), ("older", 100)):
            path = os.path.join(folder, f"{name}.json")
            judge.write_json_atomic(path, {"id": name, "outcome": "clean"})
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        judge.write_json_atomic(os.path.join(judge.verdict_dir("/tmp/transcript-b.jsonl"), "other.json"), {"id": "other"})
        self.assertEqual([v["id"] for v in judge.drain("/tmp/transcript-a.jsonl")], ["older", "newer"])
        self.assertEqual(os.listdir(folder), [])
        self.assertEqual([v["id"] for v in judge.drain("/tmp/transcript-b.jsonl")], ["other"])

    def test_drain_turns_a_corrupt_verdict_file_into_unchecked(self):
        folder = judge.verdict_dir("/tmp/transcript-a.jsonl")
        os.makedirs(folder)
        with open(os.path.join(folder, "bad.json"), "w", encoding="utf-8") as handle:
            handle.write("{half")
        verdicts = judge.drain("/tmp/transcript-a.jsonl")
        self.assertEqual(verdicts[0]["outcome"], "unchecked")
        self.assertEqual(verdicts[0]["id"], "bad")
        self.assertEqual(os.listdir(folder), [])

    def test_drain_with_no_verdicts_is_empty(self):
        self.assertEqual(judge.drain("/tmp/never-judged.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
