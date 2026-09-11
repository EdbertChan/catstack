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

PY = sys.executable
ON_HIT = "demo-hook: the last reply took back an earlier check; run reflect on it"
ANSWERS_TRUE = ["answers", [PY, "-c", "import json; print(json.dumps({'match': True}))", "{prompt}"]]
ANSWERS_FALSE = ["answers", [PY, "-c", "import json; print(json.dumps({'match': False}))", "{prompt}"]]
CRASHES = ["crashes", [PY, "-c", "import sys; sys.stderr.write('model quota exhausted'); sys.exit(3)", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


class InboxTestCase(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.work = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {judge.STATE_ENV: self.state.name})
        self.env.start()
        os.environ.pop(judge.CHILD_ENV, None)
        os.environ.pop(judge.RUNNERS_ENV, None)
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("{}\n")

    def tearDown(self):
        self.env.stop()
        self.state.cleanup()
        self.work.cleanup()

    def seed(self, *runner_entries, job_id="job-1"):
        os.environ[judge.RUNNERS_ENV] = json.dumps(list(runner_entries))
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


class TestMessages(InboxTestCase):
    def test_hit_yields_the_exact_on_hit_text_once(self):
        self.assertEqual(self.seed(ANSWERS_TRUE)["outcome"], "hit")
        self.assertEqual(inbox.messages(self.transcript), [ON_HIT])
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


if __name__ == "__main__":
    unittest.main()
