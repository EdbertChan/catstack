#!/usr/bin/env python3
from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
HOOKS_DIR = os.path.dirname(HOOK_DIR)
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

sys.path.insert(0, detect.LLM_JUDGE_DIR)
import inbox as judge_inbox  # noqa: E402
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

with open(os.path.join(FIXTURES, "real_serial_recommended.json"), encoding="utf-8") as _handle:
    REAL = json.load(_handle)

PY = sys.executable
ANSWERS_HIT = ["fake", [PY, "-c", "print('{\"match\": true, \"closest\": \"Here, one at a time\"}')", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", "print('{\"match\": false, \"closest\": \"\"}')", "{prompt}"]]
NEVER_ANSWERS = ["slow", [PY, "-c", "import time; time.sleep(3); print('{\"match\": true}')", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]
ROUTE_OUTPUT = '{"route": "delegate_invoker", "steps": ["invoker_prepare_plan_review"], "defer_to": null}'
ROUTE_COMMAND = (
    "python3 ~/.claude/skills/cat-mode/scripts/route_execution.py "
    "'{\"units\": 22, \"work_kind\": \"durable_parallel\", \"tools\": []}'"
)


def bash_call(command: str, output: str, is_error: bool = False, tool_id: str = "t1") -> list[dict]:
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": output}]}},
    ]


def menu(label: str, description: str = "", question: str = "Where should this run?") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": question, "header": "Run", "multiSelect": False, "options": [
            {"label": label, "description": description},
            {"label": "Something else", "description": ""},
        ]}]},
    }


class TestParsing(unittest.TestCase):
    def test_recommended_option_detected_in_real_payload(self):
        options = detect.recommended_options(REAL["tool_input"])
        self.assertEqual(len(options), 3)
        self.assertTrue(any("Here, one at a time (Recommended)" in option for option in options))
        self.assertTrue(any("~22 PRs need rebases" in option for option in options))

    def test_option_without_marker_is_not_selected(self):
        self.assertEqual(detect.recommended_options(menu("Here, one at a time")["tool_input"]), [])

    def test_malformed_tool_input_is_not_selected(self):
        self.assertEqual(detect.recommended_options("not a dict"), [])
        self.assertEqual(detect.recommended_options({"questions": ["x", {"options": ["y"]}]}), [])

    def test_routing_run_with_units_counts(self):
        self.assertTrue(detect.routing_ran(bash_call(ROUTE_COMMAND, ROUTE_OUTPUT)))

    def test_python_call_with_units_keyword_counts(self):
        command = "python3 -c 'import route_execution as r; print(r.route_execution(tools=[], work_kind=\"durable_parallel\", units=9))'"
        self.assertTrue(detect.routing_ran(bash_call(command, "subagent_worktree_per_unit")))

    def test_reading_the_routing_script_does_not_count(self):
        command = "cat ~/.claude/skills/cat-mode/scripts/route_execution.py"
        self.assertFalse(detect.routing_ran(bash_call(command, "units: int = 1\nreturn 'local'")))

    def test_routing_run_without_units_does_not_count(self):
        command = "python3 ~/.claude/skills/cat-mode/scripts/route_execution.py '{\"work_kind\": \"small_local\"}'"
        self.assertFalse(detect.routing_ran(bash_call(command, '{"route": "local"}')))

    def test_errored_routing_run_does_not_count(self):
        self.assertFalse(detect.routing_ran(bash_call(ROUTE_COMMAND, "Traceback ... local", is_error=True)))


class JudgedCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)
        self.wait = patch.dict(os.environ, {detect.WAIT_ENV: "15"})
        self.wait.start()

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.wait.stop()
        self.work.cleanup()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def transcript(self, lines: list[dict] | None = None) -> str:
        path = os.path.join(self.work.name, "session.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for line in lines or [{"type": "user", "message": {"role": "user", "content": "land the stacks"}}]:
                handle.write(json.dumps(line) + "\n")
        return path

    def payload(self, base: dict, lines: list[dict] | None = None) -> dict:
        event = copy.deepcopy(base)
        event["transcript_path"] = self.transcript(lines)
        return event

    def run_entry(self, event: dict) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(event))), redirect_stdout(out), redirect_stderr(err):
            try:
                claude_pretooluse.main()
            except SystemExit as exc:
                return int(exc.code or 0), out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()


class TestDetect(JudgedCase):
    def test_real_serial_recommended_option_blocks_on_judge_hit(self):
        self.use_runners(ANSWERS_HIT)
        findings = detect.detect(self.payload(REAL))
        self.assertEqual([finding.rule_id for finding in findings], [detect.RULE_ID])
        self.assertIn("route_execution.py", findings[0].message)
        self.assertIn("Here, one at a time (Recommended)", findings[0].evidence)

    def test_judge_prompt_carries_question_and_option_text(self):
        self.use_runners(ANSWERS_HIT)
        seen = []
        real_enqueue = detect._llm_judge()[0].enqueue

        def spy(job):
            seen.append(job)
            return real_enqueue(job)

        with patch.object(detect._llm_judge()[0], "enqueue", side_effect=spy):
            detect.detect(self.payload(REAL))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["hook"], "serial-option-guard")
        self.assertIn("~22 PRs need rebases or test fixes", seen[0]["prompt"])
        self.assertIn("force-push each branch myself", seen[0]["prompt"])

    def test_parallel_recommended_option_allowed_on_judge_clean(self):
        self.use_runners(ANSWERS_CLEAN)
        event = self.payload(menu("Invoker workflows (Recommended)", "One fix workflow per stuck PR."))
        self.assertEqual(detect.detect(event), [])

    def test_serial_option_without_marker_is_silent_and_asks_no_judge(self):
        self.use_runners(ANSWERS_HIT)
        event = self.payload(menu("Here, one at a time", "I rebase each of the 22 PRs myself."))
        self.assertEqual(detect.detect(event), [])
        self.assertEqual(self.jobs(), [])

    def test_routing_check_earlier_in_session_allows_and_asks_no_judge(self):
        self.use_runners(ANSWERS_HIT)
        event = self.payload(REAL, bash_call(ROUTE_COMMAND, ROUTE_OUTPUT))
        self.assertEqual(detect.detect(event), [])
        self.assertEqual(self.jobs(), [])

    def test_only_reading_the_routing_script_still_blocks(self):
        self.use_runners(ANSWERS_HIT)
        lines = bash_call("cat ~/.claude/skills/cat-mode/scripts/route_execution.py", "def route_execution(")
        self.assertEqual(len(detect.detect(self.payload(REAL, lines))), 1)

    def test_other_tool_is_ignored(self):
        self.use_runners(ANSWERS_HIT)
        event = self.payload(REAL)
        event["tool_name"] = "Bash"
        self.assertEqual(detect.detect(event), [])

    def test_subagent_payload_is_ignored(self):
        self.use_runners(ANSWERS_HIT)
        event = self.payload(REAL)
        event["agent_id"] = "a1"
        self.assertEqual(detect.detect(event), [])

    def test_unreadable_transcript_fails_open_and_says_unchecked(self):
        self.use_runners(ANSWERS_HIT)
        event = copy.deepcopy(REAL)
        event["transcript_path"] = os.path.join(self.work.name, "missing.jsonl")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.detect(event), [])
        self.assertIn("unchecked", err.getvalue())
        self.assertIn("could not be read", err.getvalue())
        self.assertEqual(self.jobs(), [])

    def test_no_transcript_fails_open_and_says_unchecked(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.detect(copy.deepcopy(REAL)), [])
        self.assertIn("unchecked", err.getvalue())

    def test_judge_with_no_runner_fails_open_and_says_unchecked(self):
        self.use_runners(MISSING)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.detect(self.payload(REAL)), [])
        self.assertIn("unchecked", err.getvalue())
        self.assertIn("not installed", err.getvalue())

    def test_slow_judge_fails_open_and_late_hit_reaches_inbox(self):
        self.use_runners(NEVER_ANSWERS)
        event = self.payload(REAL)
        err = io.StringIO()
        with patch.dict(os.environ, {detect.WAIT_ENV: "0.2"}), redirect_stderr(err):
            self.assertEqual(detect.detect(event), [])
        self.assertIn("no answer in time", err.getvalue())
        deadline = time.monotonic() + 15
        messages: list[str] = []
        while not messages and time.monotonic() < deadline:
            messages = judge_inbox.messages(event["transcript_path"])
            time.sleep(0.1)
        self.assertEqual(len(messages), 1)
        self.assertIn("serial-option-guard", messages[0])

    def test_waiting_does_not_take_other_hooks_verdicts(self):
        self.use_runners(ANSWERS_HIT)
        judge = detect._llm_judge()[0]
        event = self.payload(REAL)
        other = judge.enqueue({
            "hook": "some-other-hook", "transcript": event["transcript_path"],
            "prompt": "x", "hit_if_all_true": ["match"], "on_hit": "other hook hit",
        })
        self.assertIsNotNone(other)
        self.assertEqual(len(detect.detect(event)), 1)
        deadline = time.monotonic() + 15
        messages: list[str] = []
        while not messages and time.monotonic() < deadline:
            messages = judge_inbox.messages(event["transcript_path"])
            time.sleep(0.1)
        self.assertEqual(messages, ["other hook hit"])


class TestEntrypoint(JudgedCase):
    def test_hit_blocks_with_exit_two_and_message(self):
        self.use_runners(ANSWERS_HIT)
        code, out, err = self.run_entry(self.payload(REAL))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("serial-option-guard", err)
        self.assertIn("route_execution.py", err)

    def test_clean_verdict_allows_with_exit_zero(self):
        self.use_runners(ANSWERS_CLEAN)
        code, out, err = self.run_entry(self.payload(REAL))
        self.assertEqual((code, out), (0, ""))

    def test_garbage_stdin_fails_open(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")), redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                claude_pretooluse.main()
        self.assertEqual(caught.exception.code, 0)

    def test_mode_off_override_allows(self):
        self.use_runners(ANSWERS_HIT)
        with patch.dict(os.environ, {"CATSTACK_HOOK_MODE_SERIAL_OPTION_GUARD": "off"}):
            code, _out, _err = self.run_entry(self.payload(REAL))
        self.assertEqual(code, 0)


class TestDictionaryAndManifest(unittest.TestCase):
    def test_dictionary_loads_and_names_real_option(self):
        dictionary = phrases.load("serial-option-guard")
        self.assertEqual(dictionary["reads"], "reply")
        self.assertTrue(any("Here, one at a time (Recommended)" in text for text in dictionary["match"]))
        self.assertTrue(any("Invoker workflows (Recommended)" in text for text in dictionary["not_match"]))

    def test_manifest_wires_pretooluse_on_askuserquestion_only(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        self.assertEqual(set(fragment["hooks"]), {"PreToolUse"})
        entry = fragment["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "AskUserQuestion")
        self.assertIn("serial-option-guard/claude_pretooluse.py", entry["hooks"][0]["command"])
        self.assertGreater(entry["hooks"][0]["timeout"], detect.DEFAULT_WAIT_SECONDS)

    def test_installer_merge_is_idempotent(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings: dict = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "other"}]}]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)


if __name__ == "__main__":
    unittest.main()
