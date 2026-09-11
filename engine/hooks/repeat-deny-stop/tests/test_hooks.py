#!/usr/bin/env python3
"""Tests for the repeat-deny-stop hook (PostToolBatch).

Run: python3 -m unittest discover -s engine/hooks/repeat-deny-stop/tests -v

The deny text is the real one from the observed session: scope-lock's hard
stop denied a Bash call, then a second Bash call, with the same reason, and
the assistant went on to try Read. The tool_response shape is the one a real
Claude Code PostToolBatch payload carried for a hook-denied Bash call.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_post_tool_batch  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

SCOPE_LOCK_REASON = (
    "[python3 $HOME/.claude/hooks/scope-lock/claude_pretool_scope.py]: Second scope correction "
    "in this session: all tools are stopped. Do not continue the task or clear this with an "
    "apology/restatement. The user must explicitly invoke both `/reflect` and `automate-me`; "
    "then address the drift before resuming.\n"
)
GH_WRITE_REASON = (
    "[python3 $HOME/.claude/hooks/gh-write-verification/claude_pretooluse.py]: gh-write-verification: "
    "`gh pr edit` fails on every flag -- it eagerly queries the sunset "
    "`repository.pullRequest.projectCards` GraphQL field and exits 1 before writing anything.\n"
)


def hook_deny(tool: str, reason: str) -> str:
    return f"PreToolUse:{tool} hook error: {reason}"


def call(tool: str, response, tool_id: str = "toolu_1") -> dict:
    return {"tool_name": tool, "tool_input": {}, "tool_use_id": tool_id, "tool_response": response}


def denied(tool: str = "Bash", reason: str = SCOPE_LOCK_REASON, tool_id: str = "toolu_1") -> dict:
    return call(tool, hook_deny(tool, reason), tool_id)


def succeeded(tool_id: str = "toolu_ok") -> dict:
    return call("Bash", {"stdout": "ok\n", "stderr": "", "interrupted": False}, tool_id)


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="repeat-deny-stop-test-")
        self.state_patch = patch.object(detect, "STATE_DIR", os.path.join(self.tmp, "state"))
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def batch(self, *calls, session: str = "s1", **extra) -> dict:
        payload = {"session_id": session, "hook_event_name": "PostToolBatch", "tool_calls": list(calls)}
        payload.update(extra)
        return payload

    def run_batches(self, *batches):
        return [detect.record_batch(b)[0] for b in batches]

    def run_entry(self, payload):
        out, err = io.StringIO(), io.StringIO()
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        with patch.object(sys, "stdin", io.StringIO(raw)), redirect_stdout(out), redirect_stderr(err):
            try:
                claude_post_tool_batch.main()
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()


class TestDenyReason(unittest.TestCase):
    def test_hook_deny_reason_drops_the_tool_name(self):
        self.assertEqual(
            detect.deny_reason(hook_deny("Bash", SCOPE_LOCK_REASON)),
            detect.deny_reason(hook_deny("Read", SCOPE_LOCK_REASON)),
        )

    def test_permission_rule_deny_detected(self):
        reason = detect.deny_reason("Permission to use Bash has been denied by your rule Bash(rm:*).")
        self.assertEqual(reason, "permission denied by your rule Bash(rm:*).")

    def test_user_reject_detected(self):
        text = "The user doesn't want to proceed with this tool use. The tool use was rejected."
        self.assertEqual(detect.deny_reason(text), text)

    def test_failed_command_is_not_a_deny(self):
        self.assertIsNone(detect.deny_reason("Exit code 1\nPreToolUse:Bash hook error: quoted in a log"))

    def test_structured_tool_response_is_not_a_deny(self):
        self.assertIsNone(detect.deny_reason({"stdout": hook_deny("Bash", SCOPE_LOCK_REASON)}))


class TestRepeatDenyFires(HookTestCase):
    def test_second_identical_scope_lock_deny_fires(self):
        first, second = self.run_batches(self.batch(denied(tool_id="a")), self.batch(denied(tool_id="b")))
        self.assertIsNone(first)
        self.assertIn("Stop calling tools", second)
        self.assertIn("Second scope correction in this session", second)

    def test_switching_tools_after_a_deny_still_fires(self):
        _, second = self.run_batches(
            self.batch(denied("Bash", tool_id="a")), self.batch(denied("Read", tool_id="b"))
        )
        self.assertIsNotNone(second)

    def test_two_identical_denies_in_one_parallel_batch_fire(self):
        (message,) = self.run_batches(self.batch(denied("Bash", tool_id="a"), denied("Skill", tool_id="b")))
        self.assertIsNotNone(message)

    def test_third_identical_deny_fires_again(self):
        results = self.run_batches(*(self.batch(denied(tool_id=str(i))) for i in range(3)))
        self.assertIsNone(results[0])
        self.assertIsNotNone(results[1])
        self.assertIsNotNone(results[2])

    def test_permission_rule_deny_twice_fires(self):
        text = "Permission to use Bash has been denied by your rule Bash(rm:*)."
        _, second = self.run_batches(self.batch(call("Bash", text, "a")), self.batch(call("Bash", text, "b")))
        self.assertIsNotNone(second)

    def test_deny_read_from_transcript_when_payload_has_no_response_fires(self):
        transcript = os.path.join(self.tmp, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            for tool_id in ("a", "b"):
                handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": tool_id, "is_error": True,
                    "content": hook_deny("Bash", SCOPE_LOCK_REASON),
                }]}}) + "\n")
        bare = [{"tool_name": "Bash", "tool_input": {}, "tool_use_id": tool_id} for tool_id in ("a", "b")]
        _, second = self.run_batches(
            self.batch(bare[0], transcript_path=transcript), self.batch(bare[1], transcript_path=transcript)
        )
        self.assertIsNotNone(second)

    def test_entry_point_fires_as_additional_context_and_never_blocks(self):
        self.run_entry(self.batch(denied(tool_id="a")))
        code, out, _ = self.run_entry(self.batch(denied("Read", tool_id="b")))
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertEqual(set(body), {"hookSpecificOutput"})
        self.assertEqual(body["hookSpecificOutput"]["hookEventName"], "PostToolBatch")
        self.assertIn("Stop calling tools", body["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", body["hookSpecificOutput"])


class TestRepeatDenySilent(HookTestCase):
    def test_first_deny_is_silent(self):
        (message,) = self.run_batches(self.batch(denied()))
        self.assertIsNone(message)

    def test_two_different_deny_reasons_in_a_row_silent(self):
        _, second = self.run_batches(
            self.batch(denied(reason=SCOPE_LOCK_REASON, tool_id="a")),
            self.batch(denied(reason=GH_WRITE_REASON, tool_id="b")),
        )
        self.assertIsNone(second)

    def test_two_different_reasons_in_one_batch_silent(self):
        (message,) = self.run_batches(
            self.batch(denied(reason=SCOPE_LOCK_REASON, tool_id="a"), denied(reason=GH_WRITE_REASON, tool_id="b"))
        )
        self.assertIsNone(message)

    def test_success_between_identical_denies_is_silent(self):
        results = self.run_batches(
            self.batch(denied(tool_id="a")), self.batch(succeeded()), self.batch(denied(tool_id="b"))
        )
        self.assertEqual(results, [None, None, None])

    def test_failed_command_between_identical_denies_is_silent(self):
        results = self.run_batches(
            self.batch(denied(tool_id="a")),
            self.batch(call("Bash", "Exit code 1\nboom", "x")),
            self.batch(denied(tool_id="b")),
        )
        self.assertEqual(results, [None, None, None])

    def test_other_session_deny_is_not_counted(self):
        _, second = self.run_batches(
            self.batch(denied(tool_id="a"), session="s1"), self.batch(denied(tool_id="b"), session="s2")
        )
        self.assertIsNone(second)

    def test_no_session_id_is_silent(self):
        payload = {"hook_event_name": "PostToolBatch", "tool_calls": [denied(tool_id="a"), denied(tool_id="b")]}
        self.assertEqual(detect.record_batch(payload), (None, 0))

    def test_entry_point_prints_nothing_on_first_deny(self):
        code, out, _ = self.run_entry(self.batch(denied()))
        self.assertEqual((code, out), (0, ""))

    def test_malformed_input_fails_open(self):
        code, out, err = self.run_entry("{not json")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("unreadable hook input", err)


class TestUncheckedCalls(HookTestCase):
    def test_missing_transcript_is_unchecked_not_clean(self):
        bare = {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "u"}
        payload = self.batch(bare, transcript_path=os.path.join(self.tmp, "missing.jsonl"))
        self.assertEqual(detect.classify_calls(payload), [(detect.UNCHECKED, None)])

    def test_unreadable_call_between_identical_denies_leaves_the_count(self):
        bare = {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "u"}
        results = self.run_batches(
            self.batch(denied(tool_id="a")),
            self.batch(bare, transcript_path=os.path.join(self.tmp, "missing.jsonl")),
            self.batch(denied(tool_id="b")),
        )
        self.assertEqual(results[:2], [None, None])
        self.assertIsNotNone(results[2])

    def test_result_not_yet_in_transcript_is_unchecked(self):
        transcript = os.path.join(self.tmp, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
        bare = {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "later"}
        self.assertEqual(
            detect.classify_calls(self.batch(bare, transcript_path=transcript)), [(detect.UNCHECKED, None)]
        )

    def test_entry_point_reports_unchecked_calls_on_stderr(self):
        bare = {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "u"}
        code, out, err = self.run_entry(self.batch(bare))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no readable result", err)

    def test_corrupt_state_file_fails_open_and_recovers(self):
        path = detect.state_path(self.batch())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{corrupt")
        first, second = self.run_batches(self.batch(denied(tool_id="a")), self.batch(denied(tool_id="b")))
        self.assertIsNone(first)
        self.assertIsNotNone(second)


class TestInstall(unittest.TestCase):
    def fragment(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            return json.load(handle)

    def test_merge_adds_post_tool_batch_once_and_keeps_other_hooks(self):
        other = {"hooks": [{"type": "command", "command": "python3 other.py"}]}
        settings = {"hooks": {"PostToolBatch": [other]}, "model": "x"}
        self.assertTrue(install_claude_hook.merge_hook(settings, self.fragment()))
        self.assertFalse(install_claude_hook.merge_hook(settings, self.fragment()))
        commands = [h["command"] for e in settings["hooks"]["PostToolBatch"] for h in e["hooks"]]
        self.assertEqual(commands, ["python3 other.py", "python3 $HOME/.claude/hooks/repeat-deny-stop/claude_post_tool_batch.py"])
        self.assertEqual(settings["model"], "x")


if __name__ == "__main__":
    unittest.main()
