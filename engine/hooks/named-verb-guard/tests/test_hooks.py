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
import repro_target_proof  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
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


def subagent_payloads(path, reply):
    folder = os.path.join(os.path.dirname(path), "session", "subagents")
    os.makedirs(folder, exist_ok=True)
    agent = os.path.join(folder, "agent-a1.jsonl")
    with open(path, encoding="utf-8") as src, open(agent, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    base = {"session_id": "s", "transcript_path": path, "last_assistant_message": reply}
    return [
        dict(base, hook_event_name="SubagentStop", agent_id="a1", agent_transcript_path=agent),
        dict(base, hook_event_name="SubagentStop", agent_id="a1"),
        dict(base, hook_event_name="SubagentStop"),
    ]


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


def ran(name, result, **tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input, "result": result}


LIVE_BEFORE = ran("Bash", "node-12 role=checkout", command="svc list --live")
EDIT = ran("Edit", "ok", file_path="config/node-12.yaml")
LIVE_AFTER = ran("Bash", "node-12 timeout=30 serving", command="svc status node-12")
LIVE_REPLY = "Done.\n\n```\n$ svc status node-12\nnode-12 timeout=30 serving\n```"


class TestTargetProof(unittest.TestCase):
    def test_every_fixture_matches_its_expectation(self):
        paths = sorted(os.listdir(repro_target_proof.FIXTURES))
        self.assertTrue(any(p.startswith("fire_") for p in paths))
        self.assertTrue(any(p.startswith("clean_") for p in paths))
        for name in paths:
            with self.subTest(fixture=name):
                ok, detail = repro_target_proof.run(os.path.join(repro_target_proof.FIXTURES, name))
                self.assertTrue(ok, detail)

    def test_live_check_before_and_after_the_change_sends_nothing(self):
        self.assertEqual(detect.target_proof_gaps(LIVE_REPLY, [LIVE_BEFORE, EDIT, LIVE_AFTER]), [])

    def test_no_change_this_turn_never_sends(self):
        self.assertEqual(detect.target_proof_gaps("It is node-7.", [ran("Read", "node-7", file_path="inv.json")]), [])

    def test_output_pasted_from_before_the_change_is_not_outcome_proof(self):
        reply = "Done.\n\n```\nnode-12 role=checkout\n```"
        gaps = detect.target_proof_gaps(reply, [LIVE_BEFORE, EDIT, LIVE_AFTER])
        self.assertEqual(len(gaps), 1)
        self.assertIn("after the last change", gaps[0])

    def test_bash_cat_of_the_written_file_is_a_read_back(self):
        readback = ran("Bash", "timeout: 30", command="cat config/node-12.yaml")
        reply = "Done.\n\n```\ntimeout: 30\n```"
        self.assertTrue(detect.target_proof_gaps(reply, [LIVE_BEFORE, EDIT, readback]))

    def test_bash_cat_of_a_saved_list_is_not_a_live_query(self):
        saved = ran("Bash", "node-7", command="cat inventory.json")
        gaps = detect.target_proof_gaps(LIVE_REPLY, [saved, EDIT, LIVE_AFTER])
        self.assertEqual(gaps, ["the target came only from file reads or earlier output, not a live query this turn"])

    def test_bash_redirect_counts_as_a_change(self):
        write = ran("Bash", "", command="echo 'timeout: 30' > config/node-12.yaml")
        self.assertTrue(detect.target_proof_gaps("Done.", [write]))

    def test_tool_result_is_attached_to_its_tool_use(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "s.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "user", "message": {"content": "fix it"}}) + "\n")
                handle.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}) + "\n")
                handle.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "a.py"}]}]}}) + "\n")
            humans, tool_uses = detect.read_transcript(path)
        self.assertEqual(humans, ["fix it"])
        self.assertEqual(tool_uses[0]["result"], "a.py")

    def test_on_hit_names_the_missing_piece(self):
        with tempfile.TemporaryDirectory() as folder:
            path = transcript_with(folder, ["prove it on the live page"])
            captured = []
            with patch.object(detect, "read_transcript", return_value=(["prove it on the live page"], [EDIT])), \
                    patch.object(detect, "_judge") as judge:
                judge.return_value.is_subagent_payload.return_value = False
                judge.return_value.enqueue.side_effect = lambda job: captured.append(job) or job["id"]
                detect.enqueue_judge({"transcript_path": path, "last_assistant_message": "Done."})
        self.assertEqual(len(captured), 1)
        on_hit = captured[0]["hit_if_any_true"][detect.TARGET_PROOF_REQUEST]
        self.assertIn("Missing: the change ran before any check", on_hit)


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


class TestJudgeDelivery(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.use_runners(SLOW_CLEAN)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

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

    def queued_jobs(self, count, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(self.jobs()) < count:
            time.sleep(0.05)
        jobs = []
        for name in self.jobs():
            with open(os.path.join(self.state.name, "jobs", name), encoding="utf-8") as handle:
                jobs.append(json.load(handle))
        return jobs

    def test_bare_pass_claim_enqueues_one_job_asking_every_missing_evidence_list_and_never_blocks(self):
        path = transcript_with(self.work.name, ["test it and push"])
        err = self.run_hook({"transcript_path": path, "last_assistant_message": BARE_PASS})
        self.assertNotIn("catstack-hook-error", err)
        self.assertNotIn("named-verb-guard", err)
        jobs = self.queued_jobs(1)
        time.sleep(0.3)
        self.assertEqual(len(self.queued_jobs(1)), 1)
        self.assertEqual(jobs[0]["hook"], "named-verb-guard")
        self.assertEqual(
            sorted(jobs[0]["hit_if_any_true"]),
            sorted([detect.PROVE_REQUEST, detect.SHOW_REQUEST, detect.DELETE_REQUEST]),
        )
        for checker in (detect.PROVE_REQUEST, detect.SHOW_REQUEST, detect.DELETE_REQUEST):
            self.assertIn(checker, jobs[0]["prompt"])

    def test_one_hit_list_delivers_only_its_own_notice(self):
        answer = json.dumps({detect.SHOW_REQUEST: True, detect.PROVE_REQUEST: False, detect.DELETE_REQUEST: False})
        self.use_runners(["fake", [PY, "-c", f"print({answer!r})", "{prompt}"]])
        path = transcript_with(self.work.name, ["test it and push"])
        detect.enqueue_judge({"transcript_path": path, "last_assistant_message": BARE_PASS})
        deadline = time.monotonic() + 15
        got = []
        while time.monotonic() < deadline and not got:
            got = judge_inbox.messages(path)
            time.sleep(0.1)
        self.assertEqual(len(got), 1, got)
        self.assertIn("named-verb-guard (run/show)", got[0])
        self.assertNotIn("named-verb-guard (prove/test)", got[0])

    def test_judge_hit_is_delivered_through_the_inbox(self):
        every_list = json.dumps({checker: True for checker in detect.CHECKERS})
        self.use_runners(["fake", [PY, "-c", f"print({every_list!r})", "{prompt}"]])
        path = transcript_with(self.work.name, ["test it"])
        detect.enqueue_judge({"transcript_path": path, "last_assistant_message": FENCED_PASS + " `rm x`"})
        deadline = time.monotonic() + 15
        got = []
        while time.monotonic() < deadline and not got:
            got = judge_inbox.messages(path)
            time.sleep(0.1)
        self.assertTrue(any("named-verb-guard" in message for message in got), got)

    def test_subagent_turn_never_calls_the_judge(self):
        path = transcript_with(self.work.name, ["test it and push"])
        for payload in subagent_payloads(path, BARE_PASS):
            with self.subTest(payload=payload):
                with patch.object(detect._judge(), "enqueue", return_value="job") as enqueue:
                    self.run_hook(payload)
                enqueue.assert_not_called()

    def test_main_agent_stop_still_calls_the_judge(self):
        path = transcript_with(self.work.name, ["test it and push"])
        with patch.object(detect._judge(), "enqueue", return_value="job") as enqueue:
            self.run_hook({"hook_event_name": "Stop", "transcript_path": path, "last_assistant_message": BARE_PASS})
        enqueue.assert_called_once()

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
