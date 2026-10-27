#!/usr/bin/env python3
"""Tests for step_order.py — synthetic fixtures only, no real transcripts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import step_order  # noqa: E402

SESSION_ID = "11111111-2222-3333-4444-555555555555"


def _user_row(text: str, timestamp: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": timestamp,
    }


def _write_transcript(directory: str, rows: list[dict], session_id: str = SESSION_ID) -> str:
    path = os.path.join(directory, f"{session_id}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def _write_metrics(
    directory: str,
    runs: list[dict] | None = None,
    events: list[dict] | None = None,
    events_name: str = "events-2026-08-24.jsonl",
) -> str:
    metrics = os.path.join(directory, "metrics")
    os.makedirs(metrics, exist_ok=True)
    with open(os.path.join(metrics, "runs.jsonl"), "w", encoding="utf-8") as handle:
        for row in runs or []:
            handle.write(json.dumps(row) + "\n")
    with open(os.path.join(metrics, events_name), "w", encoding="utf-8") as handle:
        for row in events or []:
            handle.write(json.dumps(row) + "\n")
    return metrics


def _skill_event(skill: str, timestamp: str, session_id: str = SESSION_ID) -> dict:
    return {
        "hook": "skill-usage-log",
        "harness": "claude",
        "session_id": session_id,
        "action": "skill_used",
        "reason": "skill_tool",
        "skill": skill,
        "ts": timestamp,
    }


def _run_row(hook: str, outcome: str, timestamp: str, session_id: str = SESSION_ID) -> dict:
    return {
        "hook": hook,
        "harness": "claude",
        "session_id": session_id,
        "outcome": outcome,
        "ts": timestamp,
    }


class TestTaskTypeFromPrompt(unittest.TestCase):
    def test_each_named_type_has_a_matching_prompt(self):
        cases = {
            "bugfix": "fix the bug in login.ts, it crashes on submit",
            "ship-pr": "open a pull request for this branch",
            "land-stack": "land the stack once the queue is green",
            "ship-detector": "write a detector that stops this class of edit",
            "ui-change": "the layout is wrong, take a screenshot",
            "delegate": "fan out subagents over these files",
            "reflect": "/reflect on what just went wrong",
            "revert-or-merge": "revert that commit and rebase onto main",
            "other": "what time is standup",
        }
        for expected, prompt in cases.items():
            with self.subTest(task_type=expected):
                self.assertEqual(step_order.task_type_from_prompt(prompt), expected)

    def test_first_match_wins_over_a_later_pattern(self):
        self.assertEqual(
            step_order.task_type_from_prompt("fix the bug then open a PR"), "bugfix"
        )
        self.assertEqual(
            step_order.task_type_from_prompt("/reflect then fix the bug"), "reflect"
        )

    def test_no_prompt_is_undecidable_not_other(self):
        self.assertIsNone(step_order.task_type_from_prompt(None))
        self.assertIsNone(step_order.task_type_from_prompt("   "))

    def test_the_table_is_deterministic_across_calls(self):
        prompt = "land the stack and fix the bug"
        self.assertEqual(
            {step_order.task_type_from_prompt(prompt) for _ in range(20)}, {"land-stack"}
        )


class TestSkillAndHookSteps(unittest.TestCase):
    def test_only_this_session_and_only_spoke_or_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = _write_metrics(
                tmp,
                runs=[
                    _run_row("diu-stop", "spoke", "2026-08-24T12:00:01Z"),
                    _run_row("no-comments", "blocked", "2026-08-24T12:00:02Z"),
                    _run_row("hook-health", "silent", "2026-08-24T12:00:03Z"),
                    _run_row("hook-health", "crashed", "2026-08-24T12:00:04Z"),
                    _run_row("diu-stop", "spoke", "2026-08-24T12:00:05Z", session_id="other"),
                ],
                events=[
                    _skill_event("diu", "2026-08-24T12:00:00Z"),
                    _skill_event("draft-pr", "2026-08-24T12:00:06Z", session_id="other"),
                ],
            )
            hooks, hook_unchecked = step_order.hook_steps(SESSION_ID, metrics)
            skills, skill_unchecked = step_order.skill_steps(SESSION_ID, metrics)
        self.assertEqual([s["id"] for s in hooks], ["diu-stop", "no-comments"])
        self.assertEqual([s["id"] for s in skills], ["diu"])
        self.assertEqual(hook_unchecked, [])
        self.assertEqual(skill_unchecked, [])

    def test_missing_metrics_directory_is_unchecked_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "nothing-here")
            hooks, hook_unchecked = step_order.hook_steps(SESSION_ID, absent)
            skills, skill_unchecked = step_order.skill_steps(SESSION_ID, absent)
        self.assertEqual(hooks, [])
        self.assertEqual(skills, [])
        self.assertTrue(any("unchecked" in reason for reason in hook_unchecked))
        self.assertTrue(any("unchecked" in reason for reason in skill_unchecked))

    def test_a_skill_usage_unchecked_row_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = _write_metrics(
                tmp,
                events=[
                    {
                        "hook": "skill-usage-log",
                        "session_id": SESSION_ID,
                        "action": "skill_usage_unchecked",
                        "reason": "skills_unreadable",
                        "ts": "2026-08-24T12:00:00Z",
                    }
                ],
            )
            skills, unchecked = step_order.skill_steps(SESSION_ID, metrics)
        self.assertEqual(skills, [])
        self.assertTrue(any("skills_unreadable" in reason for reason in unchecked))

    def test_a_malformed_row_is_counted_not_skipped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = _write_metrics(tmp, runs=[_run_row("diu-stop", "spoke", "2026-08-24T12:00:01Z")])
            with open(os.path.join(metrics, "runs.jsonl"), "a", encoding="utf-8") as handle:
                handle.write("{not json\n")
            hooks, unchecked = step_order.hook_steps(SESSION_ID, metrics)
        self.assertEqual([s["id"] for s in hooks], ["diu-stop"])
        self.assertTrue(any("malformed" in reason for reason in unchecked))

    def test_rotated_runs_files_are_read_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = _write_metrics(tmp, runs=[_run_row("newest", "spoke", "2026-08-24T12:00:09Z")])
            for index, hook in ((1, "middle"), (2, "oldest")):
                with open(os.path.join(metrics, f"runs.jsonl.{index}"), "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(_run_row(hook, "spoke", None)) + "\n")
            hooks, _unchecked = step_order.hook_steps(SESSION_ID, metrics)
        self.assertEqual([s["id"] for s in hooks], ["oldest", "middle", "newest"])


class TestInterventionSteps(unittest.TestCase):
    def test_token_audit_kinds_become_intervention_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_transcript(
                tmp,
                [
                    _user_row("fix the bug in login.ts", "2026-08-24T12:00:00Z"),
                    _user_row("I already told you not to touch that file", "2026-08-24T12:05:00Z"),
                ],
            )
            steps, unchecked = step_order.intervention_steps(path)
        self.assertEqual([s["kind"] for s in steps], ["intervention"])
        self.assertIn("told-you", steps[0]["id"])
        self.assertTrue(any("restated-rule" in reason for reason in unchecked))

    def test_a_transcript_with_no_human_rows_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_transcript(tmp, [{"type": "assistant", "message": {"role": "assistant"}}])
            steps, unchecked = step_order.intervention_steps(path)
        self.assertEqual(steps, [])
        self.assertTrue(any("interventions unchecked" in reason for reason in unchecked))


class TestStepOrder(unittest.TestCase):
    def _session(self, tmp):
        path = _write_transcript(
            tmp,
            [
                _user_row("fix the bug in login.ts, it keeps failing", "2026-08-24T12:00:00Z"),
                _user_row("I already told you to run the repro first", "2026-08-24T12:00:30Z"),
            ],
        )
        metrics = _write_metrics(
            tmp,
            runs=[
                _run_row("no-comments", "blocked", "2026-08-24T12:00:20Z"),
                _run_row("diu-stop", "spoke", "2026-08-24T12:00:40Z"),
                _run_row("hook-health", "silent", "2026-08-24T12:00:45Z"),
            ],
            events=[
                _skill_event("principle-prove-it", "2026-08-24T12:00:10Z"),
                _skill_event("make-pr", "2026-08-24T12:00:50Z"),
            ],
        )
        return step_order.step_order(path, metrics_dir=metrics)

    def test_steps_come_back_interleaved_in_time_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self._session(tmp)
        self.assertEqual(
            [(s["kind"], s["id"]) for s in report["steps"]],
            [
                ("skill", "principle-prove-it"),
                ("hook", "no-comments"),
                ("intervention", "told-you"),
                ("hook", "diu-stop"),
                ("skill", "make-pr"),
            ],
        )
        self.assertEqual(report["step_count"], 5)
        self.assertEqual(report["undated_step_count"], 0)

    def test_task_type_comes_from_the_first_prompt_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self._session(tmp)
        self.assertEqual(report["task_type"], "bugfix")
        self.assertEqual(report["session_id"], SESSION_ID)
        self.assertTrue(report["first_prompt_excerpt"].startswith("fix the bug"))

    def test_an_autonomous_dispatch_has_no_task_type_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_transcript(
                tmp, [_user_row("Worker orientation pack:\nGoal: fix the bug", "2026-08-24T12:00:00Z")]
            )
            metrics = _write_metrics(tmp)
            report = step_order.step_order(path, metrics_dir=metrics)
        self.assertIsNone(report["task_type"])
        self.assertTrue(any("task type unchecked" in reason for reason in report["unchecked"]))

    def test_undated_steps_sort_last_and_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_transcript(tmp, [_user_row("fix the bug", "2026-08-24T12:00:00Z")])
            metrics = _write_metrics(
                tmp,
                runs=[_run_row("undated-hook", "spoke", None)],
                events=[_skill_event("diu", "2026-08-24T12:00:10Z")],
            )
            report = step_order.step_order(path, metrics_dir=metrics)
        self.assertEqual(
            [(s["kind"], s["id"]) for s in report["steps"]],
            [("skill", "diu"), ("hook", "undated-hook")],
        )
        self.assertEqual(report["undated_step_count"], 1)

    def test_a_non_claude_transcript_is_unchecked_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rollout-2026-08-24T12-00-00-abc.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            report = step_order.step_order(path, metrics_dir=tmp)
        self.assertEqual(report["harness"], "codex")
        self.assertEqual(report["steps"], [])
        self.assertTrue(any("not read yet" in reason for reason in report["unchecked"]))


class TestMain(unittest.TestCase):
    def test_writes_a_report_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_transcript(tmp, [_user_row("fix the bug", "2026-08-24T12:00:00Z")])
            metrics = _write_metrics(tmp, events=[_skill_event("diu", "2026-08-24T12:00:10Z")])
            out = os.path.join(tmp, "report", "step-order.json")
            code = step_order.main([path, "--metrics-dir", metrics, "--out", out])
            with open(out, encoding="utf-8") as handle:
                payload = json.load(handle)
        self.assertEqual(code, 0)
        self.assertEqual(payload["sessions_read"], 1)
        self.assertEqual(payload["sessions"][0]["task_type"], "bugfix")
        self.assertEqual(
            [(s["kind"], s["id"]) for s in payload["sessions"][0]["steps"]], [("skill", "diu")]
        )


if __name__ == "__main__":
    unittest.main()
