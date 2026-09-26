#!/usr/bin/env python3
"""Tests for the offscope-session UserPromptSubmit detector.

Run: python3 -m unittest discover -s engine/hooks/offscope-session/tests -v

The fixture is the real pivot: a session spends several turns on the hook
installer, then the person asks for help with their office wifi. Every judged
case drives the real background path -- enqueue, the detached judge process, a
verdict file, drain -- with a fake runner standing in for the model, so the
plumbing is proven and only the model's opinion is stubbed.
"""
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
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402

sys.path.insert(0, detect.LLM_JUDGE_DIR)

import judge  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
OFFSCOPE = ["fake", [PY, "-c", "print('{\"offscope\": true, \"why\": \"a different deliverable\"}')", judge.PROMPT_SLOT]]
ON_SCOPE = ["fake", [PY, "-c", "print('{\"offscope\": false, \"why\": \"same work\"}')", judge.PROMPT_SLOT]]
NO_KEY = ["fake", [PY, "-c", "print('{\"match\": true}')", judge.PROMPT_SLOT]]
GARBAGE = ["fake", [PY, "-c", "print('I think probably yes?')", judge.PROMPT_SLOT]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", judge.PROMPT_SLOT]]

WORK_SO_FAR = [
    ("install the scope-lock hook into cursor too", "Linked the hook directory and merged the cursor entry."),
    ("does the installer replace the settings file?", "No -- it merges only its own entry."),
    ("add a test for the merge", "Added test_merges_without_replacing_settings; it passes."),
]
PIVOT = "forget that for now. my laptop won't connect to the office wifi, help me debug that"

HARD_NEGATIVES = {
    "narrowing": "just the parser part",
    "correction": "no, use the existing helper",
    "test-of-same-work": "now write a test for it",
    "write-up": "write that up as a PR description",
    "same-code-other-angle": "why does that function take the path twice?",
}

NON_HUMAN = {
    "task-notification": "<task-notification>agent build-docs finished</task-notification>",
    "slash-command": "<local-command-stdout>/clear</local-command-stdout>",
    "system-block": "<system-reminder>The task tools have not been used recently.</system-reminder>",
}


def write_transcript(path, pairs):
    with open(path, "w", encoding="utf-8") as handle:
        for human, reply in pairs:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": human}}) + "\n")
            if reply:
                handle.write(json.dumps({
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": reply}]},
                }) + "\n")


class OffscopeCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        write_transcript(self.transcript, WORK_SO_FAR)

    def tearDown(self):
        deadline = time.monotonic() + 30
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.05)
        super().tearDown()

    def jobs(self):
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def event(self, prompt, **extra):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
            "transcript_path": self.transcript,
            "session_id": "sess-1",
        }
        payload.update(extra)
        return payload

    def wait_for_verdict(self, timeout=30):
        folder = judge.verdict_dir(detect.channel(self.transcript))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.isdir(folder) and any(n.endswith(".json") for n in os.listdir(folder)):
                return
            time.sleep(0.05)
        self.fail(f"the judge wrote no verdict for {folder} within {timeout}s")

    def judged(self, prompt):
        """Ask about `prompt`, wait for the real verdict, report it on the next prompt."""
        err = io.StringIO()
        with redirect_stderr(err):
            job = detect.build_job(self.event(prompt))
            self.assertIsNotNone(job, "the prompt was never judged")
            self.wait_for_verdict()
            findings = detect.report(self.event("and the next thing I type"))
        self.assertEqual(len(findings), 1, f"expected one finding, got {findings}")
        return findings[0], err.getvalue()


class TestGenuinePivot(OffscopeCase):
    def test_a_genuine_pivot_is_a_drift_hit(self):
        self.use_runners(OFFSCOPE)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.drift-hit")
        self.assertIn("nothing left in common with the work so far", finding.message)
        self.assertIn("fresh session", finding.message)
        self.assertIn("a different deliverable", finding.message)

    def test_the_job_carries_the_off_scope_request_verbatim(self):
        self.use_runners(OFFSCOPE)
        job = detect.build_job(self.event(PIVOT))
        self.assertEqual(job[detect.REQUEST_KEY], PIVOT)
        self.assertEqual(job["hit_if_all_true"], ["offscope"])
        self.assertEqual(job["hook"], "offscope-session")

    def test_the_judge_prompt_states_the_distinction_and_asks_for_one_json_line(self):
        job = detect.build_job(self.event(PIVOT))
        text = job["prompt"]
        self.assertIn('Return exactly one line of JSON: {"offscope": true|false', text)
        self.assertIn("a follow-up, a correction, a narrowing, a test of the same work", text)
        self.assertIn(
            "a different incident, a different deliverable, nothing left in common with what came before",
            text,
        )
        self.assertIn(PIVOT, text)
        self.assertIn("install the scope-lock hook into cursor too", text)


class TestHardNegativesStayOnScope(OffscopeCase):
    def test_each_hard_negative_is_reported_on_scope(self):
        self.use_runners(ON_SCOPE)
        for name, prompt in HARD_NEGATIVES.items():
            with self.subTest(negative=name):
                finding, _ = self.judged(prompt)
                self.assertEqual(finding.rule_id, "offscope-session.on-scope")
                self.assertIn("still the same work", finding.message)

    def test_the_dictionary_teaches_the_judge_every_hard_negative(self):
        dictionary = phrases.load("offscope-session")
        self.assertGreaterEqual(len(dictionary["not_match"]), 5)
        for name, prompt in HARD_NEGATIVES.items():
            with self.subTest(negative=name):
                self.assertIn(prompt, dictionary["not_match"])

    def test_a_hard_negative_reaches_the_judge_next_to_the_work_so_far(self):
        job = detect.build_job(self.event(HARD_NEGATIVES["narrowing"]))
        self.assertIn("THE NEW REQUEST:\njust the parser part", job["prompt"])
        self.assertIn("Added test_merges_without_replacing_settings", job["prompt"])


class TestNonHumanPromptsAreNeverJudged(OffscopeCase):
    def test_non_human_prompts_enqueue_nothing(self):
        self.use_runners(OFFSCOPE)
        for name, prompt in NON_HUMAN.items():
            with self.subTest(prompt=name):
                self.assertIsNone(detect.build_job(self.event(prompt)))
        self.assertEqual(self.jobs(), [])
        self.assertEqual(detect.detect(self.event(NON_HUMAN["task-notification"])), [])

    def test_a_non_human_prompt_reports_nothing_and_keeps_the_verdict(self):
        self.use_runners(OFFSCOPE)
        detect.build_job(self.event(PIVOT))
        self.wait_for_verdict()
        self.assertEqual(detect.report(self.event(NON_HUMAN["task-notification"])), [])
        findings = detect.report(self.event("back to it"))
        self.assertEqual([f.rule_id for f in findings], ["offscope-session.drift-hit"])

    def test_the_first_prompt_of_a_session_has_no_running_scope_to_leave(self):
        write_transcript(self.transcript, [(PIVOT, "")])
        self.assertIsNone(detect.build_job(self.event(PIVOT)))
        self.assertEqual(self.jobs(), [])


class TestUnchecked(OffscopeCase):
    def test_a_missing_model_command_is_unchecked_and_not_on_scope(self):
        self.use_runners(MISSING)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")
        self.assertNotEqual(finding.rule_id, "offscope-session.on-scope")
        self.assertIn("unchecked, not on scope", finding.message)
        self.assertIn("not installed", finding.message)

    def test_a_malformed_verdict_is_unchecked(self):
        self.use_runners(GARBAGE)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")
        self.assertIn("unchecked, not on scope", finding.message)

    def test_an_answer_missing_the_offscope_key_is_unchecked_not_on_scope(self):
        self.use_runners(NO_KEY)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")
        self.assertIn("carried no offscope true/false", finding.message)

    def test_an_errored_job_is_unchecked(self):
        finding = detect.verdict_finding({
            "id": "j1", "outcome": "unchecked", "answer": None,
            "reason": "judge error ValueError: job file holds a JSON list",
        })
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")
        self.assertIn("job file holds a JSON list", finding.message)

    def test_an_outcome_that_disagrees_with_the_answer_is_unchecked(self):
        finding = detect.verdict_finding({"id": "j2", "outcome": "clean", "answer": {"offscope": True}})
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")
        finding = detect.verdict_finding({"id": "j3", "outcome": "hit", "answer": {"offscope": "true"}})
        self.assertEqual(finding.rule_id, "offscope-session.unchecked")


class TestScopeWindow(OffscopeCase):
    def test_an_oversized_conversation_drops_the_oldest_and_still_judges(self):
        old = "OLDEST-MARKER " + ("the installer merge story " * 1200)
        self.assertGreater(len(old), detect.SCOPE_BUDGET_CHARS)
        write_transcript(self.transcript, [(old, "ok"), ("NEWEST-MARKER rename the flag", "renamed it")])
        scope = detect.running_scope(self.transcript, PIVOT)
        self.assertIn("NEWEST-MARKER", scope)
        self.assertNotIn("OLDEST-MARKER", scope)
        self.assertLessEqual(len(scope), detect.SCOPE_BUDGET_CHARS)
        self.use_runners(OFFSCOPE)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.drift-hit")

    def test_one_oversized_turn_is_clipped_to_the_budget_and_still_judges(self):
        huge = "HEAD-MARKER " + ("x" * 60_000) + " TAIL-MARKER"
        write_transcript(self.transcript, [(huge, "noted")])
        scope = detect.running_scope(self.transcript, PIVOT)
        self.assertLessEqual(len(scope), detect.SCOPE_BUDGET_CHARS)
        self.assertNotIn("HEAD-MARKER", scope)
        self.assertIn("TAIL-MARKER", scope)
        self.use_runners(ON_SCOPE)
        finding, _ = self.judged(PIVOT)
        self.assertEqual(finding.rule_id, "offscope-session.on-scope")

    def test_the_new_prompt_is_not_counted_as_its_own_scope(self):
        write_transcript(self.transcript, WORK_SO_FAR + [(PIVOT, "")])
        scope = detect.running_scope(self.transcript, PIVOT)
        self.assertNotIn("office wifi", scope)
        self.assertIn("install the scope-lock hook", scope)

    def test_non_human_turns_are_not_scope(self):
        write_transcript(self.transcript, [
            ("fix the installer merge", "fixed"),
            (NON_HUMAN["task-notification"], "acknowledged"),
        ])
        scope = detect.running_scope(self.transcript, PIVOT)
        self.assertIn("fix the installer merge", scope)
        self.assertNotIn("task-notification", scope)


class TestFailsOpen(OffscopeCase):
    def test_an_unreadable_transcript_judges_nothing_and_says_so(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.running_scope(os.path.join(self.work.name, "gone.jsonl")), "")
            self.assertIsNone(detect.build_job(self.event(PIVOT, transcript_path="")))
        self.assertIn("could not read transcript", err.getvalue())
        self.assertIn("no prompt text or transcript path", err.getvalue())

    def test_garbage_payloads_never_raise(self):
        for payload in ({}, {"prompt": ""}, "not a dict", None, {"hook_event_name": "PreToolUse"}):
            with self.subTest(payload=payload), redirect_stderr(io.StringIO()):
                self.assertEqual(detect.detect(payload), [])
                self.assertIsNone(detect.build_job(payload))
                self.assertEqual(detect.report(payload), [])

    def test_unparseable_transcript_lines_are_skipped(self):
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("not json\n")
            handle.write(json.dumps(["a list, not an object"]) + "\n")
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": "fix the merge"}}) + "\n")
        self.assertIn("fix the merge", detect.running_scope(self.transcript, PIVOT))

    def test_a_broken_judge_costs_only_this_check(self):
        class Boom:
            def drain(self, transcript):
                raise RuntimeError("verdict folder is unreadable")

            def enqueue(self, job):
                raise RuntimeError("state folder is read-only")

            def is_subagent_payload(self, payload):
                return False

        err = io.StringIO()
        with patch.object(detect, "_judge", Boom), redirect_stderr(err):
            self.assertEqual(detect.detect(self.event(PIVOT)), [])
        self.assertIn("verdict report failed: RuntimeError: verdict folder is unreadable", err.getvalue())
        self.assertIn("judge job failed: RuntimeError: state folder is read-only", err.getvalue())

    def test_a_missing_phrase_dictionary_costs_only_this_check(self):
        class NoDictionary:
            @staticmethod
            def load(checker, directory=None):
                raise ValueError("phrases/offscope-session.json: file could not be read")

        err = io.StringIO()
        with patch.object(detect, "_phrases", lambda: NoDictionary), redirect_stderr(err):
            self.assertEqual(detect.detect(self.event(PIVOT)), [])
        self.assertIn("judge job failed: ValueError", err.getvalue())

    def test_an_unreadable_verdict_file_is_unchecked(self):
        folder = judge.verdict_dir(detect.channel(self.transcript))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "broken.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        findings = detect.report(self.event("carry on"))
        self.assertEqual([f.rule_id for f in findings], ["offscope-session.unchecked"])
        self.assertIn("unreadable verdict file", findings[0].message)


if __name__ == "__main__":
    unittest.main()
