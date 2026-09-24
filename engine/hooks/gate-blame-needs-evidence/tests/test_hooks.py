#!/usr/bin/env python3
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
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
HOOKS_DIR = os.path.dirname(HOOK_DIR)
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

with open(os.path.join(FIXTURES, "real_session.json"), encoding="utf-8") as _handle:
    REAL = json.load(_handle)

PY = sys.executable
ACCEPTANCE_REPLY = (
    "I ran /reflect and automate-me, so scope-lock should be gone. "
    "Its clear condition was met and it still fires."
)
LINE_159_REPLY = (
    "scope-lock still fires because its clear condition was never met: detect.py line 159 clears the "
    "hard stop only when one user message carries both /reflect and automate-me, and they came in "
    "separate messages."
)
TABLE_NOTE = "hooks/gate-blame-needs-evidence | the model blaming a gate for a problem"
JUDGE_SAYS_HIT = json.dumps({"match": True, "closest": ACCEPTANCE_REPLY})
JUDGE_SAYS_CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({JUDGE_SAYS_HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
SLOW_CLEAN = ["slow", [PY, "-c", f"import time; time.sleep(2); print({JUDGE_SAYS_CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def lines_of(*groups):
    return detect.parse_lines(json.dumps(line) for group in groups for line in group)


def read_of(path, tool="Read", is_error=False, tool_id="t-read"):
    tool_input = {"file_path": path} if tool == "Read" else {"command": path}
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": tool, "input": tool_input}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": "..."}]}},
    ]


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


class TestGateSelection(unittest.TestCase):
    def test_unread_gate_named_in_reply_is_selected(self):
        gates = detect.unread_gates(ACCEPTANCE_REPLY, [], HOOKS_DIR)
        self.assertEqual([gate["name"] for gate in gates], ["scope-lock"])

    def test_pronoun_reply_resolves_latest_refusal_from_unread_gate(self):
        reply = "You typed both commands. It still fires."
        self.assertEqual(detect.unread_gates(reply, [], HOOKS_DIR), [])
        gates = detect.unread_gates(reply, lines_of(REAL["blocked_read"]), HOOKS_DIR)
        self.assertEqual([gate["name"] for gate in gates], ["scope-lock"])

    def test_tool_gate_wins_over_stop_feedback(self):
        reply = "You typed both commands. It still fires."
        lines = lines_of(REAL["blocked_read"], REAL["stop_feedback_after_refusal"])
        self.assertEqual([gate["name"] for gate in detect.unread_gates(reply, lines, HOOKS_DIR)], ["scope-lock"])

    def test_stop_feedback_used_when_no_tool_was_refused(self):
        reply = "You typed both commands. It still fires."
        gates = detect.unread_gates(reply, lines_of(REAL["stop_feedback_after_refusal"]), HOOKS_DIR)
        self.assertEqual([gate["name"] for gate in gates], ["diu-stop"])

    def test_successful_read_removes_gate(self):
        lines = lines_of(read_of("engine/hooks/scope-lock/detect.py"))
        self.assertEqual(detect.unread_gates(ACCEPTANCE_REPLY, lines, HOOKS_DIR), [])

    def test_successful_user_read_removes_gate(self):
        lines = [{"type": "user", "message": {"role": "user", "content":
                  "<bash-input>cat ~/.claude/hooks/scope-lock/detect.py</bash-input>"}}]
        self.assertEqual(detect.unread_gates(ACCEPTANCE_REPLY, lines, HOOKS_DIR), [])

    def test_file_line_citation_removes_gate(self):
        self.assertEqual(detect.unread_gates(LINE_159_REPLY, [], HOOKS_DIR), [])
        uncited = LINE_159_REPLY.replace("detect.py line 159", "the detector")
        self.assertEqual([gate["name"] for gate in detect.unread_gates(uncited, [], HOOKS_DIR)], ["scope-lock"])

    def test_blocked_read_does_not_remove_gate(self):
        lines = lines_of(read_of("~/.claude/hooks/scope-lock/detect.py", is_error=True))
        self.assertEqual([gate["name"] for gate in detect.unread_gates(ACCEPTANCE_REPLY, lines, HOOKS_DIR)], ["scope-lock"])

    def test_running_gate_does_not_count_as_read(self):
        lines = lines_of(read_of("python3 engine/hooks/scope-lock/detect.py < payload.json", tool="Bash"))
        self.assertEqual([gate["name"] for gate in detect.unread_gates(ACCEPTANCE_REPLY, lines, HOOKS_DIR)], ["scope-lock"])

    def test_noun_shape_and_script_names_still_resolve(self):
        self.assertEqual(
            [gate["name"] for gate in detect.unread_gates("The pr-schema gate is broken on this body.", [], HOOKS_DIR)],
            ["pr-schema-gate"],
        )
        self.assertEqual(
            [gate["name"] for gate in detect.unread_gates("lint-task-atomicity.sh has a bug in its section parser.", [], HOOKS_DIR)],
            ["lint-task-atomicity.sh"],
        )

    def test_delete_request_names_gate(self):
        case = next(c for c in REAL["fires"] if c["label"] == "2056")
        self.assertIn("scope-lock", [gate["name"] for gate in detect.unread_gates(case["reply"], [], HOOKS_DIR)])

    def test_no_gate_named_selects_nothing(self):
        self.assertEqual(detect.unread_gates("The nightly build is broken again.", [], HOOKS_DIR), [])

    def test_real_fires_queue_before_read_and_not_after(self):
        before = lines_of(REAL["blocked_read"])
        after = lines_of(REAL["blocked_read"], REAL["successful_read"])
        for case in REAL["fires"]:
            with self.subTest(line=case["label"]):
                before_names = [gate["name"] for gate in detect.unread_gates(case["reply"], before, HOOKS_DIR)]
                after_names = [gate["name"] for gate in detect.unread_gates(case["reply"], after, HOOKS_DIR)]
                self.assertTrue(before_names)
                self.assertNotIn("scope-lock", after_names)

    def test_real_review_unit_reply_after_source_read_selects_nothing(self):
        reply = REAL["silent_after_review_unit_read"]["reply"]
        self.assertEqual(detect.unread_gates(reply, lines_of(REAL["review_unit_read"]), HOOKS_DIR), [])

    def test_unlistable_hooks_dir_still_detects_by_path_shape(self):
        err = io.StringIO()
        with redirect_stderr(err):
            gates = detect.unread_gates("~/.claude/hooks/scope-lock/ still fires after both commands.", [], "/nonexistent/hooks")
        self.assertEqual([gate["name"] for gate in gates], ["scope-lock"])
        self.assertIn("cannot list /nonexistent/hooks", err.getvalue())


class TestJudgeQueue(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.use_runners(SLOW_CLEAN)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.work.cleanup()
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, lines=None, assistant_text=ACCEPTANCE_REPLY, name="session.jsonl") -> str:
        path = os.path.join(self.work.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            if lines is None:
                handle.write(transcript_line("assistant", assistant_text) + "\n")
            else:
                for line in lines:
                    handle.write(json.dumps(line) + "\n")
        return path

    def wait_for_jobs(self, count: int, seconds: float = 5) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                return jobs
            time.sleep(0.05)
        return self.jobs()

    def wait_for_messages(self, path: str, seconds: float = 15) -> list[str]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            got = judge_inbox.messages(path)
            if got:
                return got
            time.sleep(0.1)
        return []

    def run_hook(self, payload):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), patch.object(sys, "stderr", err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                self.fail(f"hook exited with {exc.code}")
        return err.getvalue()

    def queued_job(self):
        jobs = self.wait_for_jobs(1)
        self.assertEqual(len(jobs), 1)
        with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
            return json.load(handle)

    def test_dictionary_loads(self):
        dictionary = phrases.load("gate-blame-needs-evidence")
        self.assertEqual(dictionary["checker"], "gate-blame-needs-evidence")
        self.assertEqual(dictionary["reads"], "reply")
        self.assertIn("Read the gate source and cite the rule that fired as file:line", dictionary["on_hit"])

    def test_job_is_queued_when_reply_names_unread_gate(self):
        path = self.write_transcript(lines=lines_of(REAL["blocked_read"]))
        job_id = detect.enqueue_judge({"transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY})
        self.assertIsNotNone(job_id)
        job = self.queued_job()
        self.assertEqual(job["hook"], "gate-blame-needs-evidence")
        self.assertEqual(job["transcript"], path)
        self.assertIn("scope-lock", job["prompt"])
        self.assertIn("`scope-lock`", job["on_hit"])
        self.assertIn(os.path.join(HOOKS_DIR, "scope-lock", "detect.py"), job["on_hit"])

    def test_job_is_queued_for_pronoun_reply_after_unread_refusal(self):
        path = self.write_transcript(lines=lines_of(REAL["blocked_read"]))
        reply = "You typed both commands. It still fires."
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path, "last_assistant_message": reply}))
        self.assertIn("`scope-lock`", self.queued_job()["on_hit"])

    def test_nothing_queued_after_successful_read(self):
        path = self.write_transcript(lines=lines_of(read_of("engine/hooks/scope-lock/detect.py")))
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY}))
        self.assertEqual(self.jobs(), [])

    def test_nothing_queued_after_file_line_citation(self):
        path = self.write_transcript()
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path, "last_assistant_message": LINE_159_REPLY}))
        self.assertEqual(self.jobs(), [])

    def test_nothing_queued_when_no_gate_is_named(self):
        path = self.write_transcript(assistant_text="The nightly build is broken again.")
        self.assertIsNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertEqual(self.jobs(), [])

    def test_table_note_is_queued_but_judge_can_clean_it(self):
        path = self.write_transcript(assistant_text=TABLE_NOTE)
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        self.assertIn("gate-blame-needs-evidence", self.queued_job()["prompt"])

    def test_hit_verdict_reaches_agent_as_on_hit_with_gate_name(self):
        self.use_runners(ANSWERS_HIT)
        path = self.write_transcript()
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn(phrases.load("gate-blame-needs-evidence")["on_hit"], messages[0])
        self.assertIn("`scope-lock`", messages[0])

    def test_clean_verdict_says_nothing(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript(assistant_text=TABLE_NOTE)
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(judge_inbox.messages(path), [])

    def test_unchecked_verdict_says_could_not_judge(self):
        self.use_runners(MISSING)
        path = self.write_transcript()
        self.assertIsNotNone(detect.enqueue_judge({"transcript_path": path}))
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_unreadable_transcript_queues_nothing_and_writes_unchecked_message(self):
        payload = {"last_assistant_message": ACCEPTANCE_REPLY, "transcript_path": "/nonexistent/x.jsonl"}
        err = io.StringIO()
        with patch.object(sys, "stderr", err):
            detect.try_enqueue_judge(payload)
        self.assertEqual(self.jobs(), [])
        self.assertIn("unchecked", err.getvalue())
        self.assertIn("could not be read", err.getvalue())

    def test_transcript_that_cannot_be_opened_queues_nothing_and_writes_unchecked_message(self):
        path = self.write_transcript(lines=lines_of(REAL["blocked_read"]))
        err = io.StringIO()
        payload = {"transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY}
        with patch("builtins.open", side_effect=PermissionError("denied")), patch.object(sys, "stderr", err):
            self.assertIsNone(detect.enqueue_judge(payload))
        self.assertEqual(self.jobs(), [])
        self.assertIn("unchecked", err.getvalue())
        self.assertIn("could not be read", err.getvalue())

    def test_stop_hook_active_queues_nothing(self):
        path = self.write_transcript()
        self.assertIsNone(detect.enqueue_judge({
            "transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY, "stop_hook_active": True,
        }))
        self.assertEqual(self.jobs(), [])

    def test_stop_entry_always_exits_zero(self):
        path = self.write_transcript(lines=lines_of(REAL["blocked_read"]))
        err = self.run_hook({"transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY})
        self.assertEqual(err, "")
        self.assertEqual(len(self.wait_for_jobs(1)), 1)

    def test_stop_entry_garbage_stdin_fails_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_judge_error_leaves_reply_untouched(self):
        path = self.write_transcript()
        with patch.object(detect, "enqueue_judge", side_effect=RuntimeError("boom")):
            err = self.run_hook({"transcript_path": path, "last_assistant_message": ACCEPTANCE_REPLY})
        self.assertEqual(err, "catstack-hook-error gate-blame-needs-evidence: RuntimeError: boom\n")


class TestInstallWiresStopOnly(unittest.TestCase):
    def test_manifest_wires_stop_and_never_a_tool_event(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        self.assertEqual(set(fragment["hooks"]), {"Stop"})
        command = fragment["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("gate-blame-needs-evidence/claude_stop_check.py", command)

    def test_merge_is_idempotent_and_keeps_other_hooks(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        other = {"matcher": "*", "hooks": [{"type": "command", "command": "python3 other/x.py"}]}
        settings = {"hooks": {"Stop": [other]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        self.assertEqual(settings["hooks"]["Stop"][0], other)
        self.assertEqual(len(settings["hooks"]["Stop"]), 2)


if __name__ == "__main__":
    unittest.main()
