#!/usr/bin/env python3
"""Unit tests for the backgrounded LLM judge.

Run: python3 -m unittest discover -s engine/hooks/llm-judge/tests -v
"""
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

    def test_fenced_multiline_json_answer_is_read(self):
        self.use_runners(runner("fenced", "print('```json'); print('{'); print('  \"match\": true,'); print('  \"closest\": \"x\"'); print('}'); print('```')"))
        result = judge.ask("x")
        self.assertEqual(result["outcome"], "answered")
        self.assertEqual(result["answer"], {"match": True, "closest": "x"})

    def test_fence_without_language_tag_is_read(self):
        self.use_runners(runner("bare", "print('```'); print('{'); print('  \"match\": false'); print('}'); print('```')"))
        self.assertEqual(judge.ask("x")["answer"], {"match": False})

    def test_later_object_wins_across_fence_and_line(self):
        self.use_runners(runner("both", "print('```json'); print('{\"match\": false,'); print('\"closest\": \"\"}'); print('```'); print('{\"match\": true}')"))
        self.assertEqual(judge.ask("x")["answer"], {"match": True})

    def test_unclosed_fence_stays_unchecked(self):
        self.use_runners(runner("cutoff", "print('```json'); print('{'); print('  \"match\": true,')"))
        result = judge.ask("x")
        self.assertEqual(result["outcome"], "unchecked")
        self.assertIn("no JSON object line", result["attempts"][0]["reason"])

    def test_fenced_array_is_not_an_answer(self):
        self.use_runners(runner("array", "print('```json'); print('[1,'); print('2]'); print('```')"))
        self.assertEqual(judge.ask("x")["outcome"], "unchecked")

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

    def test_runner_that_exits_non_zero_is_left_out_of_the_next_ask(self):
        self.use_runners(EXIT_NONZERO, ANSWER_MATCH)
        judge.ask("first")
        result = judge.ask("second")
        self.assertEqual([a["runner"] for a in result["attempts"]], ["answers"])
        self.assertEqual(result["runner"], "answers")

    def test_missing_binary_is_left_out_of_the_next_ask(self):
        self.use_runners(MISSING_BINARY, ANSWER_MATCH)
        judge.ask("first")
        self.assertEqual([a["runner"] for a in judge.ask("second")["attempts"]], ["answers"])

    def test_left_out_runner_comes_back_after_the_window(self):
        self.use_runners(EXIT_NONZERO, ANSWER_MATCH)
        judge.ask("first")
        with patch.object(judge.time, "time", return_value=time.time() + judge.UNAVAILABLE_SECONDS + 1):
            result = judge.ask("later")
        self.assertEqual([a["runner"] for a in result["attempts"]], ["crashes", "answers"])

    def test_timeout_and_prose_do_not_leave_a_runner_out(self):
        self.use_runners(runner("hangs", "import time; time.sleep(30)"), PROSE_ONLY, ANSWER_MATCH)
        with patch.object(judge, "TIMEOUT_SECONDS", 1):
            judge.ask("first")
            result = judge.ask("second")
        self.assertEqual([a["runner"] for a in result["attempts"]], ["hangs", "rambles", "answers"])

    def test_when_every_runner_is_left_out_the_whole_table_is_tried_and_an_answer_clears_it(self):
        flaky = os.path.join(self.state.name, "flaky-ok")
        script = f"import json, os, sys; sys.exit(3) if not os.path.exists({flaky!r}) else print(json.dumps({{'match': True}}))"
        self.use_runners(runner("flaky", script))
        self.assertEqual(judge.ask("first")["outcome"], "unchecked")
        open(flaky, "w").close()
        result = judge.ask("second")
        self.assertEqual(result["runner"], "flaky")
        self.assertFalse(os.path.exists(judge.unavailable_path("flaky")))

    def test_malformed_runners_env_refuses_instead_of_running_defaults(self):
        os.environ[judge.RUNNERS_ENV] = "not json"
        with self.assertRaises(ValueError):
            judge.ask("x")

    def test_test_base_runs_only_the_local_stub(self):
        self.assertEqual([name for name, _ in judge.runners()], ["stub"])
        self.assertEqual(judge.ask("x")["answer"], {"match": False})

    def test_default_runner_order_is_claude_then_codex_then_cursor(self):
        with patch.dict(os.environ):
            os.environ.pop(judge.RUNNERS_ENV)
            self.assertEqual([name for name, _ in judge.runners()], ["claude", "codex", "cursor"])

    def test_default_claude_runner_loads_no_rules_tools_skills_or_servers(self):
        with patch.dict(os.environ):
            os.environ.pop(judge.RUNNERS_ENV)
            argv = dict(judge.runners())["claude"]
        for flag, value in (("--setting-sources", ""), ("--tools", ""), ("--system-prompt", judge.JUDGE_SYSTEM_PROMPT)):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertEqual(argv[-2:], ["--", judge.PROMPT_SLOT])

    def test_default_codex_runner_uses_the_account_model_not_a_pinned_one(self):
        with patch.dict(os.environ):
            os.environ.pop(judge.RUNNERS_ENV)
            codex_argv = dict(judge.runners())["codex"]
        self.assertNotIn("-m", codex_argv)
        self.assertNotIn("--model", codex_argv)

    def test_investigate_runner_argv_is_read_only_and_excludes_cursor(self):
        os.environ.pop(judge.RUNNERS_ENV)
        self.assertEqual(
            judge.runners("investigate"),
            [
                (
                    "codex",
                    [
                        "codex",
                        "exec",
                        "--skip-git-repo-check",
                        "--sandbox",
                        "read-only",
                        "-c",
                        "notify=[]",
                        judge.PROMPT_SLOT,
                    ],
                ),
                (
                    "claude",
                    [
                        "claude",
                        "-p",
                        "--model",
                        "haiku",
                        "--settings",
                        '{"disableAllHooks": true}',
                        "--allowedTools",
                        "Read",
                        "Grep",
                        "Glob",
                        "--disallowedTools",
                        "Write",
                        "Edit",
                        "NotebookEdit",
                        "Bash",
                        "--",
                        judge.PROMPT_SLOT,
                    ],
                ),
            ],
        )

    def test_investigate_runners_env_replaces_investigate_defaults(self):
        custom = ["probe", [PY, "-c", "print('{}')", "{prompt}"]]
        self.use_runners(custom)
        self.assertEqual(judge.runners("investigate"), [("probe", custom[1])])

    def test_investigate_job_threads_timeout_and_cwd_to_runner(self):
        os.environ.pop(judge.RUNNERS_ENV)
        path = os.path.join(self.state.name, "jobs", "investigate-job.json")
        with tempfile.TemporaryDirectory() as cwd:
            judge.write_json_atomic(path, self.job(id="investigate-job", mode="investigate", timeout_seconds=123, cwd=cwd))
            calls = []

            def capture(name, argv, prompt, timeout_seconds=judge.TIMEOUT_SECONDS, cwd=None):
                calls.append((name, timeout_seconds, cwd))
                return {"runner": name, "ok": True, "reason": "answered"}, {"match": True}

            with patch.object(judge, "run_runner", side_effect=capture):
                result = judge.run_job(path)

        self.assertEqual(result["outcome"], "hit")
        self.assertEqual(calls, [("codex", 123, cwd)])

    def test_investigate_timeout_is_capped_at_600_seconds(self):
        self.assertEqual(judge.bounded_timeout(999), 600)

    def test_non_investigate_job_still_gets_default_timeout_and_empty_temp_cwd(self):
        self.use_runners(runner("env", "import json, os; print(json.dumps({'cwd': os.getcwd(), 'entries': os.listdir('.')}))"))
        path = os.path.join(self.state.name, "jobs", "default-job.json")
        judge.write_json_atomic(path, self.job(id="default-job"))
        calls = []
        original = judge.run_runner

        def capture(name, argv, prompt, timeout_seconds=judge.TIMEOUT_SECONDS, cwd=None):
            calls.append((timeout_seconds, cwd))
            return original(name, argv, prompt, timeout_seconds=timeout_seconds, cwd=cwd)

        with patch.object(judge, "run_runner", side_effect=capture):
            result = judge.run_job(path)

        self.assertEqual(calls, [(judge.TIMEOUT_SECONDS, None)])
        self.assertEqual(result["answer"]["entries"], [])
        self.assertFalse(os.path.exists(result["answer"]["cwd"]))


class TestBuildPrompt(JudgeBehaviorTestCase):
    def test_short_fields_pass_through(self):
        prompt = judge.build_prompt("rule text", "assistant reply", "human message")
        self.assertIn("rule text", prompt)
        self.assertIn("assistant reply", prompt)
        self.assertIn("human message", prompt)

    def test_each_field_is_capped_independently(self):
        prompt = judge.build_prompt("r" * 20000, "a" * 20000, "h" * 20000)
        self.assertLessEqual(len(prompt), 3 * judge.PROMPT_FIELD_CAP + 200)
        self.assertLess(len(prompt), 16000)


class TestSubagentGuard(JudgeBehaviorTestCase):
    def test_enqueue_skips_a_transcript_path_under_subagents(self):
        self.use_runners(ANSWER_MATCH)
        with patch.object(judge.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")) as popen:
            result = judge.enqueue(self.job(transcript="/tmp/session/subagents/child.jsonl"))
        self.assertIsNone(result)
        popen.assert_not_called()
        self.assertEqual(os.listdir(self.state.name), [])

    def test_enqueue_skips_a_job_carrying_an_agent_id(self):
        self.use_runners(ANSWER_MATCH)
        with patch.object(judge.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")):
            self.assertIsNone(judge.enqueue(self.job(agent_id="sub-42")))

    def test_enqueue_skips_a_job_marked_is_sidechain(self):
        self.use_runners(ANSWER_MATCH)
        with patch.object(judge.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")):
            self.assertIsNone(judge.enqueue(self.job(isSidechain=True)))

    def test_enqueue_skips_a_transcript_whose_first_line_says_is_sidechain(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = os.path.join(folder, "session.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"isSidechain": True}) + "\n")
            self.use_runners(ANSWER_MATCH)
            with patch.object(judge.subprocess, "Popen", side_effect=AssertionError("Popen must not be called")):
                self.assertIsNone(judge.enqueue(self.job(transcript=transcript)))

    def test_enqueue_still_queues_a_normal_transcript(self):
        self.use_runners(ANSWER_MATCH)
        with patch.object(judge.subprocess, "Popen"):
            result = judge.enqueue(self.job(id="normal-job"))
        self.assertEqual(result, "normal-job")
        self.assertTrue(os.path.isfile(os.path.join(self.state.name, "jobs", "normal-job.json")))


class TestVerdict(JudgeBehaviorTestCase):
    def test_hit_when_every_hit_key_is_true(self):
        job = self.job(hit_if_all_true=["match", "sure"], rule_id="demo-hook.match")
        result = judge.verdict(job, {"outcome": "answered", "runner": "answers", "answer": {"match": True, "sure": True}, "attempts": []})
        self.assertEqual(result["outcome"], "hit")
        self.assertEqual(result["on_hit"], job["on_hit"])
        self.assertEqual(result["runner"], "answers")
        self.assertEqual(result["rule_id"], "demo-hook.match")

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
    def test_enqueue_writes_only_to_temporary_state_directory(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"HOME": home}):
                with patch.dict(os.environ):
                    os.environ.pop(judge.STATE_ENV)
                    default_state = judge.state_root()
                os.makedirs(default_state)
                with patch.object(judge.subprocess, "Popen"):
                    self.assertEqual(judge.enqueue(self.job(id="isolated-job")), "isolated-job")
            self.assertTrue(os.path.isfile(os.path.join(self.state.name, "jobs", "isolated-job.json")))
            self.assertEqual(os.listdir(default_state), [])

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

    def test_a_runner_timeout_with_no_answer_records_unchecked_exactly_once(self):
        self.use_runners(
            runner("hangs-a", "import time; time.sleep(30)"),
            runner("hangs-b", "import time; time.sleep(30)"),
        )
        path = os.path.join(self.state.name, "jobs", "timeout-job.json")
        judge.write_json_atomic(path, self.job(id="timeout-job"))
        with patch.object(judge, "TIMEOUT_SECONDS", 1):
            result = judge.run_job(path)
        self.assertEqual(result["outcome"], "unchecked")
        verdicts = judge.drain(self.job()["transcript"])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["outcome"], "unchecked")
        self.assertEqual(judge.drain(self.job()["transcript"]), [])

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

    def stage_rows(self):
        folder = os.path.join(self.state.name, "metrics")
        rows = []
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.startswith("events-"):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    rows.extend(json.loads(line) for line in handle)
        return [row for row in rows if row.get("mode_source") == "stage"]

    def test_verdict_with_hit_if_any_true_names_only_the_true_keys(self):
        job = self.job(hit_if_any_true={"a": "notice A", "b": "notice B", "c": "notice C"})
        judged = judge.verdict(job, {"outcome": "answered", "answer": {"a": True, "b": False, "c": True}, "runner": "fake"})
        self.assertEqual(judged["outcome"], "hit")
        self.assertEqual(judged["on_hit"], "notice A\nnotice C")
        clean = judge.verdict(job, {"outcome": "answered", "answer": {"a": False, "b": False}, "runner": "fake"})
        self.assertEqual(clean["outcome"], "clean")
        unchecked = judge.verdict(job, {"outcome": "unchecked", "attempts": []})
        self.assertEqual(unchecked["outcome"], "unchecked")

    def test_enqueue_records_a_queued_stage_event_keyed_by_job_id(self):
        with patch.object(judge.subprocess, "Popen"):
            judge.enqueue(self.job(id="queued-job", harness="claude"))
        rows = self.stage_rows()
        self.assertEqual([(r["action"], r["reason"], r["finding_id"], r["harness"]) for r in rows],
                         [("judge_queued", "transcript", "queued-job", "claude")])

    def test_enqueue_with_no_transcript_is_recorded_and_reported_as_an_error(self):
        err = io.StringIO()
        with patch.object(judge.subprocess, "Popen"), redirect_stderr(err):
            judge.enqueue(self.job(id="lost-job", transcript=""))
        self.assertEqual([(r["action"], r["reason"]) for r in self.stage_rows()], [("judge_queued", "no_transcript")])
        self.assertTrue(err.getvalue().startswith("catstack-hook-error demo-hook: judge job lost-job"))

    def test_run_job_records_a_finished_stage_event_with_the_verdict(self):
        self.use_runners(ANSWER_MATCH)
        path = os.path.join(self.state.name, "jobs", "job-1.json")
        judge.write_json_atomic(path, self.job())
        judge.run_job(path)
        self.assertEqual([(r["action"], r["reason"], r["finding_id"]) for r in self.stage_rows()],
                         [("judge_finished", "hit", "job-1")])

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

    def test_drain_writes_an_unchecked_event_for_a_corrupt_verdict_file(self):
        folder = judge.verdict_dir("/tmp/transcript-a.jsonl")
        os.makedirs(folder)
        with open(os.path.join(folder, "bad.json"), "w", encoding="utf-8") as handle:
            handle.write("{half")

        judge.drain("/tmp/transcript-a.jsonl")

        metrics_dir = os.environ["CATSTACK_HOOK_METRICS_DIR"]
        event_files = [name for name in os.listdir(metrics_dir) if name.endswith(".jsonl")]
        self.assertEqual(1, len(event_files))
        with open(os.path.join(metrics_dir, event_files[0]), encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(1, len(rows))
        self.assertEqual("bad", rows[0]["finding_id"])
        self.assertEqual("unchecked", rows[0]["action"])

    def test_event_write_failure_is_logged_and_does_not_stop_drain(self):
        metrics_dir = os.environ["CATSTACK_HOOK_METRICS_DIR"]
        with open(metrics_dir, "w", encoding="utf-8") as handle:
            handle.write("occupied")
        folder = judge.verdict_dir("/tmp/transcript-a.jsonl")
        judge.write_json_atomic(
            os.path.join(folder, "job-1.json"),
            {"id": "job-1", "hook": "demo-hook", "outcome": "hit"},
        )

        verdicts = judge.drain("/tmp/transcript-a.jsonl")

        self.assertEqual(["job-1"], [verdict["id"] for verdict in verdicts])
        self.assertEqual([], os.listdir(folder))
        with open(os.path.join(self.state.name, "judge.log"), encoding="utf-8") as handle:
            self.assertIn("event write failed for verdict job-1", handle.read())

    def test_drain_with_no_verdicts_is_empty(self):
        self.assertEqual(judge.drain("/tmp/never-judged.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
