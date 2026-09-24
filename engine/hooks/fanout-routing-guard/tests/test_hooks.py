#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402
import install_claude_hook  # noqa: E402

sys.path.append(detect.LLM_JUDGE_DIR)
import phrases  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

PY = sys.executable
INCIDENT = os.path.join(FIXTURES, "incident_transcript.jsonl")
INCIDENT_CURRENT_ID = "toolu_01Wv13fZYKdAhtEa7QfX6RHw"
FAKE_RUNNER = (
    "import os, sys, json\n"
    "text = sys.argv[1]\n"
    "is_direction = 'user messages the user explicitly directs' in text\n"
    "key = 'FAKE_DIRECTION' if is_direction else 'FAKE_PUSH'\n"
    "mode = os.environ.get(key, 'false')\n"
    "if mode == 'contains':\n"
    "    print(json.dumps({'match': os.environ['FAKE_NEEDLE'] in text}))\n"
    "else:\n"
    "    print(json.dumps({'match': mode == 'true'}))\n"
)
FAKE = ["fake", [PY, "-c", FAKE_RUNNER, "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]
PUSH_PROMPT = "Rebase onto master, fix all 3 findings test-first, resolve the threads, and queue it."
READ_PROMPT = "Read-only: find where the retry budget is set and report file:line."


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def launch(use_id, prompt):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"prompt": prompt, "description": "d"}}]}}


def launched(use_id):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": "Async agent launched successfully."}]}}


def bash(use_id, command, output, is_error=False):
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": "Bash", "input": {"command": command}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": use_id, "content": output, "is_error": is_error}]}},
    ]


ROUTE_CMD = "python3 ~/.claude/skills/cat-mode/scripts/route_execution.py '{\"units\": 2}'"
ROUTE_OUT = '{"route": "delegate_invoker", "steps": ["invoker_prepare_plan_review"], "defer_to": null}'


class GuardTestCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        os.environ[detect.STATE_ENV] = os.path.join(self.tmp.name, "guard-state")
        self.use_runners(FAKE)
        os.environ["FAKE_PUSH"] = "true"
        os.environ["FAKE_DIRECTION"] = "false"

    def tearDown(self):
        for key in (detect.STATE_ENV, "FAKE_PUSH", "FAKE_DIRECTION", "FAKE_NEEDLE"):
            os.environ.pop(key, None)
        self.tmp.cleanup()
        super().tearDown()

    def transcript(self, rows, name="t.jsonl"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def event(self, path, prompt, use_id="cur"):
        return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": use_id,
                "transcript_path": path, "tool_input": {"prompt": prompt, "description": "d"}}

    def two_launch_transcript(self, first=PUSH_PROMPT, second=PUSH_PROMPT, before=()):
        return self.transcript([*before, user("land the stacks"), launch("a1", first), launched("a1"),
                                launch("cur", second)])

    def run_guard(self, path, prompt, use_id="cur", wait=15):
        return detect.evaluate(self.event(path, prompt, use_id), wait=wait)


class BlocksTests(GuardTestCase):
    def test_blocks_second_publishing_launch_without_routing(self):
        outcome, message = self.run_guard(self.two_launch_transcript(), PUSH_PROMPT)
        self.assertEqual(outcome, "block")
        self.assertIn("launch 2", message)
        self.assertIn("route_execution.py", message)
        self.assertNotIn("could not decide", message)

    def test_block_fires_on_real_incident_prompts(self):
        rows = detect.read_lines(INCIDENT)
        current = next(u for r in rows for u in detect.tool_uses(r) if u["id"] == INCIDENT_CURRENT_ID)
        outcome, message = self.run_guard(INCIDENT, current["input"]["prompt"], INCIDENT_CURRENT_ID)
        self.assertEqual(outcome, "block")
        self.assertIn("launch 2", message)

    def test_blocks_when_route_script_errored(self):
        path = self.two_launch_transcript(before=bash("r1", ROUTE_CMD, "Traceback: boom", is_error=True))
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "block")

    def test_blocks_when_task_notification_arrives_mid_turn(self):
        path = self.transcript([user("land the stacks"), launch("a1", PUSH_PROMPT), launched("a1"),
                                user("<task-notification>agent a1 finished</task-notification>"),
                                launch("cur", PUSH_PROMPT)])
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "block")

    def test_block_detects_push_authority_inside_referenced_brief_file(self):
        brief = os.path.join(self.tmp.name, "BRIEF.md")
        with open(brief, "w", encoding="utf-8") as handle:
            handle.write("# Brief\nYou MAY: rebase and force-push the branches of ticket ZX-4471.\n")
        prompt = f"Read and follow {brief} first. Your name: inv-1."
        os.environ["FAKE_PUSH"] = "contains"
        os.environ["FAKE_NEEDLE"] = "ZX-4471"
        path = self.two_launch_transcript(first=prompt, second=prompt)
        self.assertEqual(self.run_guard(path, prompt)[0], "block")

    def test_unreadable_brief_file_is_named_in_judge_text(self):
        text = detect.launch_text("Read and follow /nonexistent/dir/BRIEF.md first.")
        self.assertIn("could not be read", text)

    def test_unchecked_judge_blocks_and_says_so(self):
        self.use_runners(MISSING)
        outcome, message = self.run_guard(self.two_launch_transcript(), PUSH_PROMPT)
        self.assertEqual(outcome, "block")
        self.assertIn("could not decide", message)

    def test_unchecked_when_verdict_never_arrives_blocks(self):
        slow = ["slow", [PY, "-c", "import time; time.sleep(30)", "{prompt}"]]
        self.use_runners(slow)
        outcome, message = self.run_guard(self.two_launch_transcript(), PUSH_PROMPT, wait=1)
        self.assertEqual(outcome, "block")
        self.assertIn("no verdict within", message)

    def test_hook_script_blocks_with_exit_2(self):
        path = self.two_launch_transcript()
        env = dict(os.environ, CATSTACK_HOOK_MODE_FANOUT_ROUTING_GUARD="stop", FANOUT_ROUTING_GUARD_WAIT_SECONDS="15")
        proc = subprocess.run([PY, os.path.join(HOOK_DIR, "claude_pretooluse_agent.py")],
                              input=json.dumps(self.event(path, PUSH_PROMPT)), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("fanout-routing-guard", proc.stderr)


class SilentTests(GuardTestCase):
    def test_first_launch_in_turn_is_silent(self):
        path = self.transcript([user("land the stacks"), launch("cur", PUSH_PROMPT)])
        self.assertEqual(self.run_guard(path, PUSH_PROMPT), ("allow", ""))

    def test_launch_before_last_user_prompt_not_counted(self):
        path = self.transcript([user("first task"), launch("a1", PUSH_PROMPT), launched("a1"),
                                user("next task"), launch("cur", PUSH_PROMPT)])
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "allow")

    def test_routing_result_allows(self):
        path = self.two_launch_transcript(before=bash("r1", ROUTE_CMD, ROUTE_OUT))
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "allow")

    def test_invoker_route_delegation_result_allows(self):
        cmd = "node skills/route-delegation/scripts/route-delegation.mjs '{}'"
        out = '{"route": "subagent_fanout", "steps": []}'
        path = self.two_launch_transcript(before=bash("r1", cmd, out))
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "allow")

    def test_read_only_fanout_allows(self):
        os.environ["FAKE_PUSH"] = "false"
        path = self.two_launch_transcript(first=READ_PROMPT, second=READ_PROMPT)
        self.assertEqual(self.run_guard(path, READ_PROMPT)[0], "allow")

    def test_one_publishing_among_read_only_allows(self):
        os.environ["FAKE_PUSH"] = "contains"
        os.environ["FAKE_NEEDLE"] = "ZX-9902"
        pushing = "Fix ticket ZX-9902, push the branch and open a PR."
        path = self.two_launch_transcript(first=READ_PROMPT, second=pushing)
        self.assertEqual(self.run_guard(path, pushing)[0], "allow")

    def test_user_direction_allows(self):
        os.environ["FAKE_DIRECTION"] = "true"
        self.assertEqual(self.run_guard(self.two_launch_transcript(), PUSH_PROMPT)[0], "allow")

    def test_subagent_event_is_silent(self):
        event = self.event(self.two_launch_transcript(), PUSH_PROMPT)
        event["agent_id"] = "sub-1"
        self.assertEqual(detect.evaluate(event, wait=1), ("allow", ""))

    def test_non_agent_tool_is_silent(self):
        self.assertEqual(detect.evaluate({"tool_name": "Bash", "tool_input": {"command": "ls"}}), ("allow", ""))

    def test_cached_clean_verdict_allows_without_new_job(self):
        os.environ["FAKE_PUSH"] = "false"
        path = self.two_launch_transcript(first=READ_PROMPT, second=READ_PROMPT)
        self.assertEqual(self.run_guard(path, READ_PROMPT)[0], "allow")
        self.use_runners(MISSING)
        self.assertEqual(self.run_guard(path, READ_PROMPT, wait=0)[0], "allow")


class UncheckedInputTests(GuardTestCase):
    def test_unreadable_transcript_fails_open_with_unchecked(self):
        event = self.event(os.path.join(self.tmp.name, "missing.jsonl"), PUSH_PROMPT)
        outcome, message = detect.evaluate(event, wait=1)
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", message)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(detect.detect(event), [])
        self.assertIn("UNCHECKED", err.getvalue())

    def test_no_transcript_path_fails_open_with_unchecked(self):
        event = self.event("", PUSH_PROMPT)
        event.pop("transcript_path")
        self.assertEqual(detect.evaluate(event, wait=1)[0], "unchecked")

    def test_malformed_cache_is_treated_empty(self):
        path = self.two_launch_transcript()
        cache = detect.state_path(path)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "block")
        self.assertIn("unreadable verdict cache", err.getvalue())

    def test_garbage_transcript_lines_are_skipped(self):
        path = os.path.join(self.tmp.name, "garbage.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json\n" + json.dumps(user("go")) + "\n" + json.dumps(launch("cur", PUSH_PROMPT)) + "\n")
        self.assertEqual(self.run_guard(path, PUSH_PROMPT)[0], "allow")


class DecisionTableTests(unittest.TestCase):
    def test_decision_table(self):
        H, C, U = detect.HIT, detect.CLEAN, detect.UNCHECKED
        cases = [
            ((C, [H], C), "allow"),
            ((H, [C], C), "allow"),
            ((H, [H], H), "allow"),
            ((H, [H], C), "block"),
            ((U, [U], U), "block"),
            ((H, [None], C), None),
            ((None, [H], C), None),
            ((H, [C, H], C), "block"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(detect.decision(*args), expected)


class DictionaryAndInstallTests(unittest.TestCase):
    def test_dictionaries_load(self):
        for name in (detect.PUSH_CHECKER, detect.DIRECTION_CHECKER):
            self.assertEqual(phrases.load(name)["checker"], name)

    def test_install_merge_is_idempotent_and_keeps_other_entries(self):
        with open(install_claude_hook.FRAGMENT_PATH) as handle:
            fragment = json.load(handle)
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other.py"}]}
        settings, changed = install_claude_hook.merge_hook({"hooks": {"PreToolUse": [other]}}, fragment)
        self.assertTrue(changed)
        again, changed_again = install_claude_hook.merge_hook(settings, fragment)
        self.assertFalse(changed_again)
        self.assertEqual(len(again["hooks"]["PreToolUse"]), 2)
        self.assertEqual(again["hooks"]["PreToolUse"][1]["matcher"], "Agent|Task")


if __name__ == "__main__":
    unittest.main()
