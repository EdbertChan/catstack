#!/usr/bin/env python3
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import claude_prompt_submit  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import inbox  # noqa: E402
import judge  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
ON_HIT = "demo-hook: the last reply took back an earlier check; run reflect on it"
ANSWERS_TRUE = ["answers", [PY, "-c", "import json; print(json.dumps({'match': True}))", "{prompt}"]]
ANSWERS_FALSE = ["answers", [PY, "-c", "import json; print(json.dumps({'match': False}))", "{prompt}"]]
CRASHES = ["crashes", [PY, "-c", "import sys; sys.stderr.write('model quota exhausted'); sys.exit(3)", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


class InboxTestCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("{}\n")

    def tearDown(self):
        self.work.cleanup()
        super().tearDown()

    def seed(self, *runner_entries, job_id="job-1"):
        self.use_runners(*runner_entries)
        job_path = os.path.join(self.state.name, "jobs", f"{job_id}.json")
        judge.write_json_atomic(job_path, {
            "id": job_id,
            "hook": "demo-hook",
            "transcript": self.transcript,
            "prompt": "did the reply retract a check?",
            "hit_if_all_true": ["match"],
            "on_hit": ON_HIT,
        })
        return judge.run_job(job_path)

    def seed_verdict(self, verdict, job_id="job-1"):
        judge.write_json_atomic(os.path.join(judge.verdict_dir(self.transcript), f"{job_id}.json"), verdict)

    def run_claude(self, stdin_text):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(stdin_text)), redirect_stdout(out), redirect_stderr(err):
            claude_prompt_submit.main()
        return out.getvalue(), err.getvalue()

    def run_cursor(self, stdin_text):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(stdin_text)), redirect_stdout(out), redirect_stderr(err):
            cursor_session.main()
        return json.loads(out.getvalue()), err.getvalue()

    def run_codex(self, argv):
        err = io.StringIO()
        with patch.object(sys, "argv", ["codex_notify.py", *argv]), redirect_stderr(err):
            codex_notify.main()
        return err.getvalue()

    def claude_payload(self):
        return json.dumps({"hook_event_name": "UserPromptSubmit", "transcript_path": self.transcript, "prompt": "next"})


class TestJudgePrompt(InboxTestCase):
    def write_transcript(self, path, *records):
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def test_last_turn_reads_the_most_recent_human_and_assistant_messages(self):
        self.write_transcript(
            self.transcript,
            {"type": "user", "message": {"role": "user", "content": "first question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "first answer"}},
            {"type": "user", "message": {"role": "user", "content": "second question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "second answer"}},
        )
        self.assertEqual(inbox.last_turn(self.transcript), ("second question", "second answer"))

    def test_last_turn_ignores_hook_feedback_and_skill_bodies(self):
        """`isMeta` rows are the harness talking, not the person."""
        self.write_transcript(
            self.transcript,
            {"type": "user", "message": {"role": "user", "content": "real question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "real answer"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "llm-judge: hook feedback"}},
        )
        self.assertEqual(inbox.last_turn(self.transcript), ("real question", "real answer"))

    def test_last_turn_ignores_tool_result_rows(self):
        """Claude Code files a tool result as a `user` row with no `isMeta`."""
        self.write_transcript(
            self.transcript,
            {"type": "user", "message": {"role": "user", "content": "real question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "real answer"}},
            {
                "type": "user",
                "toolUseResult": {"stdout": "ok"},
                "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
            },
            {
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "content": "x"},
                    {"type": "text", "text": "tool output text"},
                ]},
            },
        )
        self.assertEqual(inbox.last_turn(self.transcript), ("real question", "real answer"))

    def test_last_turn_ignores_helper_agent_rows(self):
        """A sidechain or agent-id row is a helper agent, not the main turn."""
        self.write_transcript(
            self.transcript,
            {"type": "user", "message": {"role": "user", "content": "real question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "real answer"}},
            {"type": "user", "isSidechain": True, "message": {"role": "user", "content": "helper prompt"}},
            {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": "helper reply"}},
            {"type": "assistant", "agentId": "sub-1", "message": {"role": "assistant", "content": "child reply"}},
        )
        self.assertEqual(inbox.last_turn(self.transcript), ("real question", "real answer"))

    def test_judge_prompt_quotes_the_real_turn_not_the_harness_rows(self):
        self.write_transcript(
            self.transcript,
            {"type": "user", "message": {"role": "user", "content": "real question"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "real answer"}},
            {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": "helper reply"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "hook feedback"}},
        )
        prompt = inbox.judge_prompt("rule text", self.transcript)
        self.assertIn("real question", prompt)
        self.assertIn("real answer", prompt)
        self.assertNotIn("helper reply", prompt)
        self.assertNotIn("hook feedback", prompt)

    def test_last_turn_on_missing_transcript_is_empty(self):
        self.assertEqual(inbox.last_turn(self.transcript + ".gone"), ("", ""))

    def test_judge_prompt_is_under_16000_chars_for_a_transcript_over_200000_chars(self):
        huge_transcript = os.path.join(self.work.name, "huge.jsonl")
        self.write_transcript(
            huge_transcript,
            {"type": "user", "message": {"role": "user", "content": "h" * 120000}},
            {"type": "assistant", "message": {"role": "assistant", "content": "a" * 120000}},
        )
        self.assertGreater(os.path.getsize(huge_transcript), 200000)
        prompt = inbox.judge_prompt("Rule: the reply must not retract a check without evidence.", huge_transcript)
        self.assertLess(len(prompt), 16000)

    def test_is_subagent_event_true_for_agent_id(self):
        self.assertTrue(inbox.is_subagent_event({"agent_id": "sub-1", "transcript_path": self.transcript}))

    def test_is_subagent_event_true_for_is_sidechain(self):
        self.assertTrue(inbox.is_subagent_event({"isSidechain": True, "transcript_path": self.transcript}))

    def test_is_subagent_event_true_for_subagents_path(self):
        sub_dir = os.path.join(self.work.name, "subagents")
        os.makedirs(sub_dir, exist_ok=True)
        sub_transcript = os.path.join(sub_dir, "child.jsonl")
        with open(sub_transcript, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.assertTrue(inbox.is_subagent_event({"transcript_path": sub_transcript}))

    def test_is_subagent_event_false_for_a_normal_payload(self):
        self.assertFalse(inbox.is_subagent_event({"transcript_path": self.transcript}))

    def test_enqueue_judge_skips_a_subagent_event(self):
        with patch.object(judge, "enqueue") as mock_enqueue:
            result = inbox.enqueue_judge(
                {"hook": "demo-hook", "rule_text": "rule", "on_hit": ON_HIT, "hit_if_all_true": ["match"]},
                {"agent_id": "sub-1", "transcript_path": self.transcript},
            )
        self.assertIsNone(result)
        mock_enqueue.assert_not_called()

    def test_enqueue_judge_queues_a_normal_event(self):
        with patch.object(judge, "enqueue", return_value="job-1") as mock_enqueue:
            result = inbox.enqueue_judge(
                {"hook": "demo-hook", "rule_text": "rule", "on_hit": ON_HIT, "hit_if_all_true": ["match"]},
                {"transcript_path": self.transcript},
            )
        self.assertEqual(result, "job-1")
        mock_enqueue.assert_called_once()
        queued_job = mock_enqueue.call_args[0][0]
        self.assertEqual(queued_job["transcript"], self.transcript)
        self.assertNotIn("rule_text", queued_job)


class TestMessages(InboxTestCase):
    def test_hit_yields_the_exact_on_hit_text_once(self):
        self.assertEqual(self.seed(ANSWERS_TRUE)["outcome"], "hit")
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])
        self.assertEqual(inbox.messages(self.transcript), [])

    def test_hit_with_report_appends_report(self):
        report = "model saw a quoted rollback"
        self.seed_verdict({"outcome": "hit", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"report": report}})
        found = inbox.messages(self.transcript)
        self.assertEqual(found, [f"{ON_HIT} {report}"])
        self.assertTrue(found[0].endswith(f" {report}"), found)

    def test_hit_without_report_equals_on_hit_exactly(self):
        self.seed_verdict({"outcome": "hit", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"match": True}})
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])

    def test_hit_report_is_clipped_to_600_characters(self):
        report = "x" * 700
        self.seed_verdict({"outcome": "hit", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"report": report}})
        self.assertEqual(inbox.messages(self.transcript), [f"{ON_HIT} {'x' * 600}"])

    def test_hit_number_or_list_report_is_ignored(self):
        self.seed_verdict({"outcome": "hit", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"report": 5}}, job_id="a")
        self.seed_verdict({"outcome": "hit", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"report": ["detail"]}}, job_id="b")
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT, ON_HIT])

    def test_clean_with_report_yields_nothing(self):
        self.seed_verdict({"outcome": "clean", "hook": "demo-hook", "on_hit": ON_HIT, "answer": {"report": "ignored"}})
        self.assertEqual(inbox.messages(self.transcript), [])

    def test_unchecked_yields_one_reason_per_runner(self):
        self.assertEqual(self.seed(MISSING, CRASHES)["outcome"], "unchecked")
        self.assertEqual(
            inbox.messages(self.transcript),
            ["llm-judge: demo-hook could not judge the last reply: ghost: not installed; crashes: exit 3: model quota exhausted"],
        )

    def test_clean_yields_nothing(self):
        self.assertEqual(self.seed(ANSWERS_FALSE)["outcome"], "clean")
        self.assertEqual(inbox.messages(self.transcript), [])
        self.assertEqual(os.listdir(judge.verdict_dir(self.transcript)), [])

    def test_empty_store_yields_nothing(self):
        self.assertEqual(inbox.messages(self.transcript), [])

    def test_unreadable_verdict_file_is_unchecked_not_clean(self):
        folder = judge.verdict_dir(self.transcript)
        os.makedirs(folder)
        with open(os.path.join(folder, "broken.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        found = inbox.messages(self.transcript)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("llm-judge: unknown hook could not judge the last reply: unreadable verdict file"), found)

    def test_verdicts_for_another_transcript_are_not_delivered(self):
        self.seed(ANSWERS_TRUE)
        self.assertEqual(inbox.messages(self.transcript + ".other"), [])
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])


class TestClaudePromptSubmit(InboxTestCase):
    def test_hit_is_delivered_as_additional_context_once(self):
        self.seed(ANSWERS_TRUE, job_id="a")
        self.seed(MISSING, job_id="b")
        out, err = self.run_claude(self.claude_payload())
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ON_HIT + "\n\nllm-judge: demo-hook could not judge the last reply: ghost: not installed",
        }})
        self.assertEqual(self.run_claude(self.claude_payload()), ("", ""))

    def test_clean_prints_nothing(self):
        self.seed(ANSWERS_FALSE)
        self.assertEqual(self.run_claude(self.claude_payload()), ("", ""))

    def test_empty_store_prints_nothing(self):
        self.assertEqual(self.run_claude(self.claude_payload()), ("", ""))

    def test_malformed_stdin_exits_zero_with_a_stderr_line(self):
        result = subprocess.run(
            [PY, os.path.join(LIB_DIR, "claude_prompt_submit.py")],
            input="{not json", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("llm-judge: could not read the UserPromptSubmit payload", result.stderr)

    def test_missing_transcript_path_says_unchecked_on_stderr(self):
        self.seed(ANSWERS_TRUE)
        out, err = self.run_claude(json.dumps({"prompt": "next"}))
        self.assertEqual(out, "")
        self.assertIn("no transcript path", err)
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])


class TestCursorSession(InboxTestCase):
    def test_hit_is_delivered_as_followup_message(self):
        self.seed(ANSWERS_TRUE)
        result, err = self.run_cursor(json.dumps({"transcript_path": self.transcript}))
        self.assertEqual(result, {"followup_message": ON_HIT})
        self.assertEqual(err, "")
        self.assertEqual(self.run_cursor(json.dumps({"transcript_path": self.transcript})), ({}, ""))

    def test_clean_prints_empty_object(self):
        self.seed(ANSWERS_FALSE)
        self.assertEqual(self.run_cursor(json.dumps({"transcript_path": self.transcript})), ({}, ""))

    def test_malformed_stdin_prints_empty_object_and_a_stderr_line(self):
        result, err = self.run_cursor("{not json")
        self.assertEqual(result, {})
        self.assertIn("llm-judge: could not read the Cursor stop payload", err)

    def test_missing_transcript_says_unchecked_on_stderr(self):
        result, err = self.run_cursor(json.dumps({"transcript_path": self.transcript + ".gone"}))
        self.assertEqual(result, {})
        self.assertIn("no transcript path", err)


class TestCodexNotify(InboxTestCase):
    def payload(self, **extra):
        return json.dumps({"type": "agent-turn-complete", "transcript_path": self.transcript, **extra})

    def test_hit_is_printed_on_stderr(self):
        self.seed(ANSWERS_TRUE)
        self.assertEqual(self.run_codex([self.payload()]), ON_HIT + "\n")
        self.assertEqual(self.run_codex([self.payload()]), "")

    def test_clean_prints_nothing(self):
        self.seed(ANSWERS_FALSE)
        self.assertEqual(self.run_codex([self.payload()]), "")

    def test_chains_to_the_prior_notify_command(self):
        marker = os.path.join(self.work.name, "chained.txt")
        prior = [PY, "-c", f"import sys; open({marker!r}, 'w').write(sys.argv[-1])"]
        self.run_codex(prior + [self.payload()])
        with open(marker, encoding="utf-8") as handle:
            self.assertEqual(json.loads(handle.read())["type"], "agent-turn-complete")

    def test_other_event_types_are_ignored(self):
        self.seed(ANSWERS_TRUE)
        self.assertEqual(self.run_codex([json.dumps({"type": "approval-requested", "transcript_path": self.transcript})]), "")
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])

    def test_malformed_payload_writes_a_stderr_line(self):
        self.assertIn("llm-judge: could not read the Codex notify payload", self.run_codex(["{not json"]))

    def test_no_transcript_says_unchecked_on_stderr(self):
        self.assertIn("no transcript path", self.run_codex([json.dumps({"type": "agent-turn-complete", "thread-id": "t1"})]))



REAL_CODEX_NOTIFY_KEYS = ["client", "cwd", "input-messages", "last-assistant-message", "thread-id", "turn-id", "type"]
THREAD = "01a0ce9a-301b-7d42-bb5c-b9a9a4cfe8c6"


class TestTranscriptResolution(InboxTestCase):
    def setUp(self):
        super().setUp()
        sessions = os.path.join(self.work.name, "codex-sessions")
        day = os.path.join(sessions, "2026", "09", "23")
        os.makedirs(day)
        self.rollout = os.path.join(day, f"rollout-2026-09-23T22-10-06-{THREAD}.jsonl")
        with open(self.rollout, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.sessions_env = patch.dict(os.environ, {"CATSTACK_CODEX_SESSIONS_DIR": sessions})
        self.sessions_env.start()

    def tearDown(self):
        self.sessions_env.stop()
        super().tearDown()

    def real_codex_payload(self):
        payload = {
            "type": "agent-turn-complete",
            "thread-id": THREAD,
            "turn-id": "01a0ce9a-30dc-73f1-bfe6-ccce644446e1",
            "cwd": self.work.name,
            "client": "codex_exec",
            "input-messages": ["Reply with the single word ok."],
            "last-assistant-message": "ok",
        }
        self.assertEqual(sorted(payload), REAL_CODEX_NOTIFY_KEYS)
        return payload

    def test_real_codex_notify_payload_resolves_to_its_rollout_file(self):
        self.assertEqual(inbox.resolve_transcript(self.real_codex_payload()), self.rollout)

    def test_hit_for_a_codex_rollout_reaches_the_next_codex_notify(self):
        self.transcript = self.rollout
        self.seed(ANSWERS_TRUE)
        self.assertEqual(self.run_codex([json.dumps(self.real_codex_payload())]), ON_HIT + "\n")

    def test_unknown_or_unsafe_thread_id_resolves_to_nothing(self):
        for thread in ("0000000-0000-not-there", "../../etc", "*"):
            with self.subTest(thread=thread):
                self.assertEqual(inbox.resolve_transcript({"thread-id": thread}), "")

    def test_a_subagent_verdict_is_delivered_to_the_parent_session(self):
        subagent = os.path.join(self.transcript[: -len(".jsonl")], "subagents", "agent-a1.jsonl")
        os.makedirs(os.path.dirname(subagent))
        with open(subagent, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        parent = self.transcript
        self.transcript = subagent
        self.seed(ANSWERS_TRUE)
        self.assertEqual(inbox.messages(parent), [ON_HIT])
        self.assertEqual(inbox.messages(parent), [])

if __name__ == "__main__":
    unittest.main()
