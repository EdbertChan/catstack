#!/usr/bin/env python3
"""Regression tests for the per-session scope-lock hook."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretool_scope  # noqa: E402
import claude_prompt_scope  # noqa: E402
import codex_pretool_scope  # noqa: E402
import codex_prompt_scope  # noqa: E402
import cursor_before_submit  # noqa: E402
import cursor_pretool_scope  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402
import install_codex_hook  # noqa: E402
import install_cursor_hook  # noqa: E402


def fixture_messages(name: str) -> list[str]:
    messages: list[str] = []
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("type") != "user":
                continue
            messages.append(row["message"]["content"])
    return messages


def fixture_rows(name: str) -> list[dict]:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def append_assistant(path: str, text: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }) + "\n")


def run_main(main, payload: dict) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class TestUnreadableInput(unittest.TestCase):
    """Pin what happens to input the detector cannot read.

    Two files feed a decision here, and they resolve in opposite directions
    on purpose: a corrupt state file means no lock is in force, while an
    unreadable transcript means no scope contract was recorded, so a lock
    already in force is not released by a file that could not be read.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_state_dir = detect.STATE_DIR
        detect.STATE_DIR = self.tmp.name

    def tearDown(self) -> None:
        detect.STATE_DIR = self.saved_state_dir
        self.tmp.cleanup()

    def test_fails_open_when_the_state_file_is_malformed(self):
        payload = {"session_id": "session-corrupt"}
        with open(detect.state_path(payload), "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        self.assertEqual(detect.load_state(payload), {})

    def test_fails_open_when_the_state_file_holds_a_non_object(self):
        payload = {"session_id": "session-list"}
        with open(detect.state_path(payload), "w", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]")
        self.assertEqual(detect.load_state(payload), {})

    def test_unreadable_transcript_records_no_contract_so_a_lock_holds(self):
        payload = {"session_id": "session-2", "transcript_path": "/nonexistent/session.jsonl"}
        self.assertEqual(detect.recorded_contract(payload, 0), "")

    def test_missing_transcript_counts_zero_lines_rather_than_guessing(self):
        payload = {"session_id": "session-3", "transcript_path": "/nonexistent/session.jsonl"}
        self.assertEqual(detect._line_count(detect._transcript_path(payload)), 0)

    def test_unreadable_transcript_evidence_records_no_correction(self):
        transcript = os.path.join(self.tmp.name, "unreadable.jsonl")
        payload = {
            "session_id": "session-unreadable-transcript",
            "transcript_path": transcript,
            "prompt": "what are you doing",
        }
        real_open = open

        def open_except_transcript(path, *args, **kwargs):
            if path == transcript:
                raise PermissionError("transcript is unreadable")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=open_except_transcript):
            evidence = detect.mutating_work_after_previous_user(payload, payload["prompt"])
            result = detect.process_prompt(payload)

        self.assertIsNone(evidence)
        self.assertNotIn("phase", result)
        self.assertNotIn("correction_counts", result)


class ScopeLockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        detect.STATE_DIR = self.tmp.name
        self.transcript = os.path.join(self.tmp.name, "session.jsonl")
        open(self.transcript, "w", encoding="utf-8").close()
        self.base = {"session_id": "session-1", "transcript_path": self.transcript}
        self.append_user("Please complete the requested work.")
        self.append_tool("Write")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prompt(self, text: str, *, mutating_work: bool = True) -> dict:
        if mutating_work:
            self.append_tool("Write")
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": text},
            }) + "\n")
        return detect.process_prompt({**self.base, "prompt": text})

    def append_tool(self, name: str) -> None:
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": name, "input": {}}],
                },
            }) + "\n")

    def append_user(self, text: str) -> None:
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": text},
            }) + "\n")

    def tool(self, name: str = "Bash") -> tuple[bool, str]:
        return detect.tool_block_reason({**self.base, "tool_name": name})


class TestDetection(ScopeLockCase):
    def test_repeated_drift_fixture_detects_same_class(self):
        messages = fixture_messages("repeated_drift.jsonl")
        self.assertEqual([detect.correction_class(m, True) for m in messages], ["scope", "scope"])

    def test_ordinary_product_confusion_does_not_trigger(self):
        [message] = fixture_messages("ordinary_product_confusion.jsonl")
        self.assertIsNone(detect.correction_class(message, True))

    def test_explicit_scope_expansion_does_not_trigger(self):
        [message] = fixture_messages("explicit_scope_expansion.jsonl")
        self.assertIsNone(detect.correction_class(message, True))

    def test_execution_routing_fixture_detects_every_real_correction(self):
        messages = fixture_messages("execution_routing_correction.jsonl")
        self.assertEqual(len(messages), 4)
        self.assertEqual(
            [detect.correction_class(m, True) for m in messages],
            ["scope", "scope", "scope", "scope"],
        )

    def test_interrogative_correction_triggers(self):
        self.assertEqual(
            detect.correction_class("wait why are you running this locally and not in invoker?", True),
            "scope",
        )
        self.assertEqual(
            detect.correction_class("why did we do this with subagents rather than the queue?", True),
            "scope",
        )

    def test_proposal_shaped_correction_triggers(self):
        self.assertEqual(
            detect.correction_class(
                "if we are backtesting this, should we doing this the same way we did in invoker?",
                True,
            ),
            "scope",
        )
        self.assertEqual(
            detect.correction_class(
                "we should parallelize these with invoker instead. we shouldn't do this locally.",
                True,
            ),
            "scope",
        )

    def test_substitution_correction_triggers(self):
        self.assertEqual(
            detect.correction_class(
                "also im a bit surprised we elected to use subagents instead of invoker execution. why?",
                True,
            ),
            "scope",
        )

    def test_genuine_question_fixture_does_not_trigger(self):
        messages = fixture_messages("genuine_question.jsonl")
        self.assertEqual(len(messages), 4)
        self.assertEqual(
            [detect.correction_class(m, True) for m in messages],
            [None, None, None, None],
        )

    def test_question_about_an_artifact_rather_than_the_agent_does_not_trigger(self):
        for message in (
            "why is the pretool exit code 2 and not 1?",
            "how does the state file get keyed when the payload has no session id?",
            "can you explain why the contract has to land in a prior turn?",
            "does invoker support this, or do we need to run it locally first?",
        ):
            self.assertIsNone(detect.correction_class(message, True), message)

    def test_pasted_transcript_trigger_phrase_far_from_end_does_not_trigger(self):
        # Mirrors a real session: a pasted terminal transcript quoting a
        # different tool's "do not use Invoker" ~700 chars before the end
        # of a long message, with no live correction actually intended.
        filler = "x" * 500
        text = (
            "analyze this session and tell me why it is blocked: "
            + filler
            + ' the model wrote "do not use Invoker" in its own gate text '
            + filler
        )
        self.assertIsNone(detect.correction_class(text, True))

    def test_trigger_phrase_within_tail_window_still_triggers(self):
        text = "x" * 200 + " ok whatever, just do it locally"
        self.assertEqual(detect.correction_class(text, True), "scope")

    def test_automated_task_notification_never_triggers_correction(self):
        text = (
            "<task-notification>\n<task-id>abc123</task-id>\n"
            "<result>Evidence: the user said \"do not use Invoker\" and "
            "\"just do it locally\" in the quoted transcript.</result>\n"
            "</task-notification>"
        )
        self.assertIsNone(detect.correction_class(text, True))

    def test_automated_task_notification_never_satisfies_reflection_check(self):
        text = (
            "<task-notification>\n<result>The fix is: the user must type "
            "/reflect and automate-me to clear the hard stop.</result>\n"
            "</task-notification>"
        )
        self.assertFalse(detect.reflection_invoked(text))

    def test_bare_reflect_without_leading_slash_still_satisfies_check(self):
        # A harness CLI can intercept a leading "/reflect" as an unknown
        # command before the hook ever sees it (observed: Codex CLI).
        self.assertTrue(detect.reflection_invoked("please reflect and automate-me now"))
        self.assertTrue(detect.reflection_invoked("/reflect and automate-me now"))


class TestStateMachine(ScopeLockCase):
    def test_correction_wording_with_mutating_work_records_correction(self):
        self.append_user("Please delegate the requested implementation.")
        self.append_tool("Agent")

        result = self.prompt("what are you doing", mutating_work=False)

        self.assertEqual(result["phase"], "contract_required")
        self.assertEqual(result["correction_counts"], {"scope": 1})

    def test_correction_wording_without_mutating_work_records_nothing(self):
        self.append_user("Please inspect the current status.")
        self.append_tool("Read")

        result = self.prompt("what are you doing", mutating_work=False)

        self.assertNotIn("phase", result)
        self.assertNotIn("correction_counts", result)

    def test_explicit_expansion_with_mutating_work_stays_excluded(self):
        result = self.prompt(
            "what are you doing? Also include the deployment scripts.",
            mutating_work=True,
        )

        self.assertNotIn("phase", result)
        self.assertNotIn("correction_counts", result)

    def test_real_conversation_contract_then_ok_do_it_allows_write(self):
        rows = fixture_rows("contract_continuation.jsonl")
        request = rows[0]["message"]["content"]
        contract = rows[1]["message"]["content"][0]["text"]
        continuation = rows[2]["message"]["content"]

        self.append_user(request)
        code, output, _ = run_main(codex_prompt_scope.main, {**self.base, "prompt": request})
        self.assertEqual(code, 0)
        self.assertIn("SCOPE CONTRACT:", json.loads(output)["hookSpecificOutput"]["additionalContext"])

        append_assistant(self.transcript, contract)
        self.append_user(continuation)
        code, output, _ = run_main(codex_prompt_scope.main, {**self.base, "prompt": continuation})
        self.assertEqual(code, 0)
        self.assertEqual(output, "")

        code, output, _ = run_main(codex_pretool_scope.main, {**self.base, "tool_name": "Write"})
        self.assertEqual(code, 0)
        self.assertEqual(output, "")

    def test_new_shape_corrections_trigger_hard_stop_on_the_second_hit(self):
        first, second, third, fourth = fixture_messages("execution_routing_correction.jsonl")
        self.assertEqual(self.prompt(first)["phase"], "contract_required")
        self.assertEqual(self.prompt(second)["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])
        self.assertEqual(self.prompt(third)["phase"], "hard_stop")
        self.assertEqual(self.prompt(fourth)["phase"], "hard_stop")

    def test_one_new_shape_correction_does_not_hard_stop(self):
        state = self.prompt("wait why are you running this locally and not in invoker?")
        self.assertEqual(state["phase"], "contract_required")
        self.assertEqual(state["correction_counts"]["scope"], 1)
        self.assertFalse(self.tool("Read")[0])

    def test_genuine_question_does_not_advance_correction_state(self):
        for message in fixture_messages("genuine_question.jsonl"):
            self.assertNotIn("phase", self.prompt(message))
        self.assertFalse(self.tool("Write")[0])

    def test_repeated_drift_fixture_triggers_hard_stop(self):
        first, second = fixture_messages("repeated_drift.jsonl")
        self.prompt(first)
        append_assistant(self.transcript, "You're right. I will only fix it locally.")
        self.assertTrue(self.tool("Write")[0])
        result = self.prompt(second)
        self.assertEqual(result["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])

    def test_first_correction_blocks_mutating_and_external_tools(self):
        result = self.prompt("wtf are you doing? Just fix it locally.")
        self.assertEqual(result["phase"], "contract_required")
        for tool in ("Bash", "Write", "Edit", "WebFetch", "mcp__github__create_pull_request"):
            blocked, reason = self.tool(tool)
            self.assertTrue(blocked, tool)
            self.assertIn("SCOPE CONTRACT:", reason)

    def test_first_correction_allows_local_read_only_tools(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        for tool in ("Read", "Grep", "Glob", "LS"):
            blocked, _ = self.tool(tool)
            self.assertFalse(blocked, tool)

    def test_one_line_scope_contract_releases_first_gate_but_persists_lock(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "SCOPE CONTRACT: Change only local catstack hook files; do not touch DO1 or queues.")
        blocked, _ = self.tool("Write")
        self.assertFalse(blocked)
        state = detect.load_state(self.base)
        self.assertEqual(state["phase"], "locked")
        self.assertIn("local catstack", state["contract"].lower())

    def test_contract_is_consumed_on_next_prompt_before_ok_do_it(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "SCOPE CONTRACT: Change only local catstack hook files; do not touch queues.")
        result = self.prompt("ok do it")
        self.assertEqual(result["phase"], "locked")
        self.assertFalse(self.tool("Write")[0])

    def test_apology_and_plain_restatement_do_not_clear_first_gate(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "Sorry. I understand: I will only fix it locally.")
        blocked, _ = self.tool("Write")
        self.assertTrue(blocked)

    def test_second_same_class_correction_hard_stops_every_tool(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        append_assistant(self.transcript, "SCOPE CONTRACT: Fix only local catstack support.")
        self.assertFalse(self.tool("Write")[0])
        result = self.prompt(
            "why did you expand into babysitting the merge queue? All I am asking is catstack support."
        )
        self.assertEqual(result["phase"], "hard_stop")
        append_assistant(self.transcript, "SCOPE CONTRACT: Sorry; catstack only.")
        for tool in ("Read", "Grep", "Bash", "Write", "WebFetch"):
            blocked, reason = self.tool(tool)
            self.assertTrue(blocked, tool)
            self.assertIn("/reflect", reason)
            self.assertIn("automate-me", reason)

    def test_reflect_without_automate_me_does_not_clear_hard_stop(self):
        self.prompt("what are you doing? just do this locally")
        self.prompt("you are drifting again; that is not what I asked")
        self.prompt("/reflect")
        self.assertTrue(self.tool("Read")[0])

    def test_reflect_and_automate_me_clear_hard_stop(self):
        self.prompt("what are you doing? just do this locally")
        self.prompt("you are drifting again; that is not what I asked")
        result = self.prompt("/reflect and automate-me this repeated scope drift")
        self.assertEqual(result["phase"], "reflection_acknowledged")
        self.assertFalse(self.tool("Read")[0])

    def test_bare_reflect_without_slash_clears_hard_stop(self):
        # Regression for a harness (Codex CLI) whose slash-command parser
        # intercepts a leading "/reflect" before it reaches the hook,
        # permanently stranding a hard_stop session with no other exit.
        self.prompt("what are you doing? just do this locally")
        self.prompt("you are drifting again; that is not what I asked")
        result = self.prompt("ok please reflect and automate-me now")
        self.assertEqual(result["phase"], "reflection_acknowledged")
        self.assertFalse(self.tool("Read")[0])

    def hard_stop(self) -> None:
        self.prompt("what are you doing? just do this locally")
        self.assertEqual(
            self.prompt("you are drifting again; that is not what I asked")["phase"], "hard_stop"
        )

    def still_needed(self) -> str:
        instruction = detect.prompt_instruction(detect.load_state(self.base))
        self.assertIn("Still needed:", instruction)
        return instruction.split("Still needed:", 1)[1]

    def test_reflect_then_automate_me_in_separate_prompts_clears_hard_stop(self):
        self.hard_stop()
        self.assertEqual(self.prompt("/reflect")["phase"], "hard_stop")
        result = self.prompt("automate-me")
        self.assertEqual(result["phase"], "reflection_acknowledged")
        self.assertFalse(self.tool("Read")[0])
        self.assertFalse(self.tool("Write")[0])

    def test_automate_me_then_reflect_in_separate_prompts_clears_hard_stop(self):
        self.hard_stop()
        self.assertEqual(self.prompt("automate-me")["phase"], "hard_stop")
        self.assertEqual(self.prompt("/reflect")["phase"], "reflection_acknowledged")
        self.assertFalse(self.tool("Bash")[0])

    def test_reflect_alone_does_not_clear_hard_stop_and_names_automate_me_missing(self):
        self.hard_stop()
        self.prompt("/reflect")
        self.prompt("ok, now what?")
        self.assertEqual(detect.load_state(self.base)["phase"], "hard_stop")
        for tool in ("Read", "Write"):
            blocked, reason = self.tool(tool)
            self.assertTrue(blocked, tool)
            self.assertIn("automate-me", reason.split("Still needed:", 1)[1])
        needed = self.still_needed()
        self.assertIn("automate-me", needed)
        self.assertNotIn("/reflect", needed)

    def test_automate_me_alone_does_not_clear_hard_stop_and_names_reflect_missing(self):
        self.hard_stop()
        self.prompt("automate-me")
        self.assertTrue(self.tool("Read")[0])
        needed = self.still_needed()
        self.assertIn("/reflect", needed)
        self.assertNotIn("automate-me", needed)

    def test_prompt_hook_names_the_missing_invocation(self):
        self.hard_stop()
        self.append_user("/reflect")
        code, out, _ = run_main(claude_prompt_scope.main, {**self.base, "prompt": "/reflect"})
        self.assertEqual(code, 0)
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("automate-me", context.split("Still needed:", 1)[1])
        self.assertNotIn("/reflect", context.split("Still needed:", 1)[1])

    def test_automated_notification_never_records_an_invocation_during_hard_stop(self):
        self.hard_stop()
        self.prompt(
            "<task-notification>\n<result>the user must type /reflect</result>\n"
            "</task-notification>"
        )
        self.prompt("automate-me")
        self.assertEqual(detect.load_state(self.base)["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])

    def test_invocations_before_the_hard_stop_do_not_count_toward_it(self):
        self.prompt("what are you doing? just do this locally")
        self.prompt("/reflect")
        self.prompt("you are drifting again; that is not what I asked")
        self.prompt("automate-me")
        self.assertEqual(detect.load_state(self.base)["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])

    def test_next_correction_after_split_clear_returns_to_contract_stage(self):
        self.hard_stop()
        self.prompt("/reflect")
        self.prompt("automate-me")
        state = detect.load_state(self.base)
        self.assertEqual(state["correction_counts"], {})
        self.assertNotIn("reflect_seen", state)
        self.assertNotIn("automate_seen", state)
        result = self.prompt("you are drifting again; that is not what I asked")
        self.assertEqual(result["phase"], "contract_required")
        self.assertEqual(result["correction_counts"]["scope"], 1)
        self.assertFalse(self.tool("Read")[0])
        blocked, reason = self.tool("Write")
        self.assertTrue(blocked)
        self.assertIn("SCOPE CONTRACT:", reason)

    def test_next_correction_after_same_message_clear_returns_to_contract_stage(self):
        self.hard_stop()
        self.prompt("/reflect and automate-me this repeated scope drift")
        result = self.prompt("you are drifting again; that is not what I asked")
        self.assertEqual(result["phase"], "contract_required")

    def test_a_new_hold_does_not_inherit_invocations_from_the_last_one(self):
        self.hard_stop()
        self.prompt("/reflect")
        self.prompt("automate-me")
        self.hard_stop()
        self.prompt("/reflect")
        self.assertEqual(detect.load_state(self.base)["phase"], "hard_stop")
        self.assertTrue(self.tool("Read")[0])
        self.assertIn("automate-me", self.still_needed())

    def test_automated_notification_does_not_advance_correction_state(self):
        result = self.prompt(
            "<task-notification>\n<result>Evidence: the transcript quotes "
            '"just do it locally" and "do not use Invoker".</result>\n'
            "</task-notification>"
        )
        self.assertNotIn("phase", result)
        self.assertFalse(self.tool("Write")[0])

    def test_first_gate_instructs_ending_the_turn(self):
        self.assertIn("end this turn", detect.FIRST_GATE.lower())


class TestHarnessWrappers(ScopeLockCase):
    def test_claude_prompt_injects_scope_contract_instruction(self):
        prompt = "wtf are you doing? Just fix it locally."
        self.append_user(prompt)
        payload = {**self.base, "prompt": prompt}
        code, out, _ = run_main(claude_prompt_scope.main, payload)
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertIn("SCOPE CONTRACT:", body["hookSpecificOutput"]["additionalContext"])

    def test_claude_pretool_blocks_with_exit_two(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, _, err = run_main(claude_pretool_scope.main, {**self.base, "tool_name": "Write"})
        self.assertEqual(code, 2)
        self.assertIn("SCOPE CONTRACT:", err)

    def test_cursor_before_submit_records_lock(self):
        prompt = "wtf are you doing? Just fix it locally."
        self.append_user(prompt)
        payload = {**self.base, "prompt": prompt}
        code, out, _ = run_main(cursor_before_submit.main, payload)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"continue": True})
        self.assertEqual(detect.load_state(self.base)["phase"], "contract_required")

    def test_cursor_pretool_blocks(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, out, _ = run_main(cursor_pretool_scope.main, {**self.base, "tool_name": "Write"})
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertFalse(body["continue"])
        self.assertIn("SCOPE CONTRACT:", body["user_message"])

    def test_codex_prompt_injects_scope_contract_instruction(self):
        prompt = "wtf are you doing? Just fix it locally."
        self.append_user(prompt)
        payload = {**self.base, "prompt": prompt}
        code, out, _ = run_main(codex_prompt_scope.main, payload)
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertIn("SCOPE CONTRACT:", body["hookSpecificOutput"]["additionalContext"])

    def test_codex_pretool_denies_with_native_decision(self):
        self.prompt("wtf are you doing? Just fix it locally.")
        code, out, _ = run_main(codex_pretool_scope.main, {**self.base, "tool_name": "Bash"})
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("SCOPE CONTRACT:", decision["permissionDecisionReason"])


class TestInstallers(unittest.TestCase):
    def test_claude_installer_merges_prompt_and_pretool_once(self):
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": []}]}}
        merged = install_claude_hook.merge_hooks(settings)
        merged_twice = install_claude_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["Stop"]), 1)

    def test_cursor_installer_merges_prompt_and_pretool_once(self):
        hooks = {"version": 1, "hooks": {"stop": [{"type": "prompt", "prompt": "keep"}]}}
        merged = install_cursor_hook.merge_hooks(hooks)
        merged_twice = install_cursor_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["beforeSubmitPrompt"]), 1)
        self.assertEqual(len(merged["hooks"]["preToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["stop"]), 1)

    def test_codex_installer_merges_native_prompt_and_pretool_once(self):
        hooks = {"hooks": {"Stop": [{"hooks": []}]}}
        merged = install_codex_hook.merge_hooks(hooks)
        merged_twice = install_codex_hook.merge_hooks(merged)
        self.assertEqual(merged, merged_twice)
        self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 1)
        self.assertEqual(len(merged["hooks"]["Stop"]), 1)

    def test_codex_installer_migrates_legacy_pretool_without_dropping_it(self):
        legacy = {
            "pre_tool_use": [{
                "matcher": "exec",
                "hooks": [{"type": "command", "command": "python3 existing.py"}],
            }]
        }
        merged = install_codex_hook.merge_hooks(legacy)
        self.assertNotIn("pre_tool_use", merged)
        commands = [
            hook["command"]
            for entry in merged["hooks"]["PreToolUse"]
            for hook in entry["hooks"]
        ]
        self.assertIn("python3 existing.py", commands)
        self.assertEqual(merged["hooks"]["PreToolUse"][0]["matcher"], "Bash")


if __name__ == "__main__":
    unittest.main()
