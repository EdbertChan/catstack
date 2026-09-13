#!/usr/bin/env python3
"""Tests for the named-verb-guard Stop hook.

Run: python3 -m unittest discover -s engine/hooks/named-verb-guard/tests -v

Whether the user asked is judged by the background model, so these tests pin
the local half: which request types are sent to the judge given the reply's
evidence and the turn's tool calls, and that a judge hit is delivered through
the llm-judge inbox without blocking the reply. No test calls a real model.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import judge  # noqa: E402
import phrases  # noqa: E402

PY = sys.executable
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": "test it"})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
SLOW_CLEAN = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]

TAGGED = "{{CAT-UNVERIFIED: the suite result -- cannot verify: it did not finish inside the sandbox timeout}}"
BARE_PASS = "Fixed the lot builder and re-ran the suite. All tests pass, pushed to the branch."
FENCED_PASS = (
    "Fixed the lot builder.\n\n```\n$ python3 -m pytest tests/test_lots.py -q\n"
    "12 passed in 0.41s\n```\n\nPushed as 3f2a9c1."
)
URL_REPLY = "The dashboard is live: https://example.com/dash"


def transcript_with(folder, user_texts, tool_uses_after_last=()):
    path = os.path.join(folder, "session.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for text in user_texts:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
            handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "working"}]}}) + "\n")
        for name, tool_input in tool_uses_after_last:
            handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": name, "input": tool_input}]}}) + "\n")
    return path


def checkers(message, humans, tool_uses=()):
    return [checker for checker, _ in detect.pending_requests(message, list(humans), list(tool_uses))]


def tool(name, **tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input}


class TestPendingRequests(unittest.TestCase):
    def test_bare_pass_claim_fires_prove_show_and_delete_checks(self):
        self.assertEqual(
            checkers(BARE_PASS, ["test it and push"]),
            [detect.PROVE_REQUEST, detect.SHOW_REQUEST, detect.DELETE_REQUEST],
        )

    def test_second_user_message_fires_proof_demand_check_with_every_message(self):
        pending = detect.pending_requests(BARE_PASS, ["prove it", "are you sure?"], [])
        self.assertEqual(pending[0][0], detect.PROOF_DEMAND)
        self.assertIn("prove it", pending[0][1])
        self.assertIn("are you sure?", pending[0][1])

    def test_mutating_tool_call_fires_stop_check(self):
        self.assertIn(detect.STOP_REQUEST, checkers(FENCED_PASS, ["stop"], [tool("Edit", file_path="a.py")]))

    def test_fenced_output_does_not_send_prove_or_show(self):
        pending = checkers(FENCED_PASS, ["test it"])
        self.assertNotIn(detect.PROVE_REQUEST, pending)
        self.assertNotIn(detect.SHOW_REQUEST, pending)

    def test_file_line_reference_does_not_send_prove(self):
        self.assertNotIn(detect.PROVE_REQUEST, checkers("The guard is at detect.py:42.", ["repro it"]))

    def test_url_does_not_send_show_but_still_sends_prove(self):
        pending = checkers(URL_REPLY, ["show me the dashboard"])
        self.assertNotIn(detect.SHOW_REQUEST, pending)
        self.assertIn(detect.PROVE_REQUEST, pending)

    def test_delete_command_this_turn_does_not_send_delete(self):
        pending = checkers("Done.", ["delete the temp dir"], [tool("Bash", command="rm -rf /tmp/x")])
        self.assertNotIn(detect.DELETE_REQUEST, pending)

    def test_delete_command_in_backticks_does_not_send_delete(self):
        self.assertNotIn(detect.DELETE_REQUEST, checkers("Ran `git revert abc123`.", ["revert it"]))

    def test_read_only_tool_calls_never_send_stop(self):
        self.assertNotIn(detect.STOP_REQUEST, checkers(BARE_PASS, ["stop"], [tool("Read", file_path="a.py")]))

    def test_single_user_message_never_sends_proof_demand(self):
        self.assertNotIn(detect.PROOF_DEMAND, checkers(BARE_PASS, ["prove it"]))

    def test_well_formed_tag_sends_nothing(self):
        self.assertEqual(checkers(TAGGED, ["test it"], [tool("Edit", file_path="a.py")]), [])

    def test_clarifying_question_reply_sends_nothing(self):
        self.assertEqual(checkers("Which test file do you mean?", ["test it"]), [])

    def test_empty_user_message_sends_nothing(self):
        self.assertEqual(checkers(BARE_PASS, ["  "]), [])

    def test_no_user_message_sends_nothing(self):
        self.assertEqual(checkers(BARE_PASS, []), [])

    def test_hook_feedback_line_is_not_the_users_message_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = transcript_with(folder, ["test it", "Stop hook feedback:\nsomething"])
            humans, _ = detect.read_transcript(path)
        self.assertEqual(humans, ["test it"])


class TestDictionaries(unittest.TestCase):
    def test_every_checker_dictionary_loads_and_reads_the_user(self):
        for checker in detect.CHECKERS:
            dictionary = phrases.load(checker)
            self.assertEqual(dictionary["checker"], checker)
            self.assertEqual(dictionary["reads"], "user")
            self.assertIn("named-verb-guard", dictionary["on_hit"])

    def test_old_intent_patterns_are_gone(self):
        for name in ("NAMED_VERB_RE", "STOP_RE", "PROOF_RE", "named_verbs", "proof_poll_count", "decide"):
            self.assertFalse(hasattr(detect, name), name)


class TestJudgeDelivery(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.work = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            judge.STATE_ENV: self.state.name,
            judge.RUNNERS_ENV: json.dumps([SLOW_CLEAN]),
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

    def jobs(self):
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def queued_hooks(self, count, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(self.jobs()) < count:
            time.sleep(0.05)
        hooks = []
        for name in self.jobs():
            try:
                with open(os.path.join(self.state.name, "jobs", name), encoding="utf-8") as handle:
                    hooks.append(json.load(handle)["hook"])
            except (OSError, ValueError):
                continue
        return sorted(hooks)

    def run_hook(self, payload):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), patch.object(sys, "stderr", err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                self.fail(f"hook exited with {exc.code}; it must never block")
        return err.getvalue()

    def test_bare_pass_claim_enqueues_one_job_per_missing_evidence_and_never_blocks(self):
        path = transcript_with(self.work.name, ["test it and push"])
        err = self.run_hook({"transcript_path": path, "last_assistant_message": BARE_PASS})
        self.assertNotIn("catstack-hook-error", err)
        self.assertNotIn("named-verb-guard", err)
        self.assertEqual(
            self.queued_hooks(3),
            sorted([detect.PROVE_REQUEST, detect.SHOW_REQUEST, detect.DELETE_REQUEST]),
        )

    def test_judge_hit_is_delivered_through_the_inbox(self):
        os.environ[judge.RUNNERS_ENV] = json.dumps([ANSWERS_HIT])
        path = transcript_with(self.work.name, ["test it"])
        detect.enqueue_judge({"transcript_path": path, "last_assistant_message": FENCED_PASS + " `rm x`"})
        deadline = time.monotonic() + 15
        got = []
        while time.monotonic() < deadline and not got:
            got = judge_inbox.messages(path)
            time.sleep(0.1)
        self.assertTrue(any("named-verb-guard" in message for message in got), got)

    def test_stop_hook_active_enqueues_nothing(self):
        path = transcript_with(self.work.name, ["test it"])
        self.assertEqual(detect.enqueue_judge({
            "transcript_path": path, "last_assistant_message": BARE_PASS, "stop_hook_active": True,
        }), [])
        self.assertEqual(self.jobs(), [])

    def test_missing_transcript_fails_open(self):
        self.assertEqual(detect.enqueue_judge({
            "transcript_path": "/nonexistent/x.jsonl", "last_assistant_message": BARE_PASS,
        }), [])

    def test_garbage_stdin_prints_nothing(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")), patch.object(sys, "stderr", err):
            claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(self.jobs(), [])

    def test_unreadable_dictionary_is_reported_not_silent(self):
        path = transcript_with(self.work.name, ["test it"])
        with patch.object(detect, "PHRASES_PATH", "/nonexistent/phrases.py"):
            detect._phrases.cache_clear()
            err = self.run_hook({"transcript_path": path, "last_assistant_message": BARE_PASS})
        self.assertIn("catstack-hook-error named-verb-guard", err)


if __name__ == "__main__":
    unittest.main()
