#!/usr/bin/env python3
"""Tests for the gate-blame-needs-evidence Stop hook.

Run: python3 -m unittest discover -s engine/hooks/gate-blame-needs-evidence/tests -v

tests/fixtures/real_session.json holds verbatim replies from the session this
hook came from: fourteen replies that blamed the scope-lock hook ("its
stated clear condition is met and it still fires", "the scope-lock hook has
three defects", "remove it", `rm -f ~/.claude/hooks/scope-lock/state*.json`)
before any successful read of its source, the blocked `cat` of the hook
that must not count as a read, the successful `cat` of detect.py that must,
and a review-unit reply made after its checker's source was read, which
must stay silent.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
HOOKS_DIR = os.path.dirname(HOOK_DIR)
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

with open(os.path.join(FIXTURES, "real_session.json"), encoding="utf-8") as _handle:
    REAL = json.load(_handle)

ACCEPTANCE_REPLY = (
    "I ran /reflect and automate-me, so scope-lock should be gone. "
    "Its clear condition was met and it still fires."
)
LINE_159_REPLY = (
    "scope-lock still fires because its clear condition was never met: detect.py line 159 clears the "
    "hard stop only when one user message carries both /reflect and automate-me, and they came in "
    "separate messages."
)


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


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_entry(payload_text):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(payload_text)):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestFiresOnUnreadGateBlame(unittest.TestCase):
    def test_fires_on_acceptance_reply_with_no_read_of_the_gate(self):
        message = detect.decide_stop_from_lines(ACCEPTANCE_REPLY, [], HOOKS_DIR)
        self.assertIsNotNone(message)
        self.assertIn("`scope-lock`", message)
        self.assertIn(os.path.join(HOOKS_DIR, "scope-lock", "detect.py"), message)

    def test_fires_on_each_real_blame_reply_when_only_read_was_blocked(self):
        lines = lines_of(REAL["blocked_read"])
        for case in REAL["fires"]:
            with self.subTest(line=case["label"]):
                message = detect.decide_stop_from_lines(case["reply"], lines, HOOKS_DIR)
                self.assertIsNotNone(message, case["reply"][:120])
                self.assertIn("`scope-lock`", message)

    def test_fires_on_pronoun_blame_by_resolving_the_latest_refusal(self):
        reply = "You typed both commands. It still fires."
        self.assertIsNone(detect.decide_stop_from_lines(reply, [], HOOKS_DIR))
        message = detect.decide_stop_from_lines(reply, lines_of(REAL["blocked_read"]), HOOKS_DIR)
        self.assertIn("`scope-lock`", message)

    def test_fires_on_tool_gate_not_on_stop_hook_that_sent_the_last_reply_back(self):
        reply = "You typed both commands. It still fires."
        lines = lines_of(REAL["blocked_read"], REAL["stop_feedback_after_refusal"])
        blames = detect.unread_blames(reply, lines, HOOKS_DIR)
        self.assertEqual([b["gate"]["name"] for b in blames], ["scope-lock"])
        lines = lines_of(REAL["blocked_read"], REAL["successful_read"], REAL["stop_feedback_after_refusal"])
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines, HOOKS_DIR))

    def test_fires_on_stop_hook_feedback_only_when_no_tool_was_refused(self):
        reply = "You typed both commands. It still fires."
        blames = detect.unread_blames(reply, lines_of(REAL["stop_feedback_after_refusal"]), HOOKS_DIR)
        self.assertEqual([b["gate"]["name"] for b in blames], ["diu-stop"])

    def test_fires_when_reply_quotes_the_refusal_message_but_not_the_rule(self):
        case = next(c for c in REAL["fires"] if c["label"] == "1939")
        self.assertIn("```", case["reply"])
        self.assertIsNotNone(detect.decide_stop_from_lines(case["reply"], lines_of(REAL["blocked_read"]), HOOKS_DIR))

    def test_fires_when_a_different_gate_was_read(self):
        lines = lines_of(read_of("engine/hooks/diu-stop/detect.py"))
        self.assertIsNotNone(detect.decide_stop_from_lines(ACCEPTANCE_REPLY, lines, HOOKS_DIR))

    def test_fires_when_gate_was_run_rather_than_read(self):
        lines = lines_of(read_of("python3 engine/hooks/scope-lock/detect.py < payload.json", tool="Bash"))
        self.assertIsNotNone(detect.decide_stop_from_lines(ACCEPTANCE_REPLY, lines, HOOKS_DIR))

    def test_fires_when_read_tool_errored(self):
        lines = lines_of(read_of("~/.claude/hooks/scope-lock/detect.py", is_error=True))
        self.assertIsNotNone(detect.decide_stop_from_lines(ACCEPTANCE_REPLY, lines, HOOKS_DIR))

    def test_flags_gate_named_by_noun_shape_and_resolves_its_directory(self):
        message = detect.decide_stop_from_lines("The pr-schema gate is broken on this body.", [], HOOKS_DIR)
        self.assertIn("`pr-schema-gate`", message)

    def test_flags_checker_script_blame(self):
        message = detect.decide_stop_from_lines("lint-task-atomicity.sh has a bug in its section parser.", [], HOOKS_DIR)
        self.assertIn("`lint-task-atomicity.sh`", message)

    def test_flags_request_to_delete_hook_files(self):
        case = next(c for c in REAL["fires"] if c["label"] == "2056")
        blames = detect.blamed_gates(case["reply"], [], HOOKS_DIR)
        self.assertIn("scope-lock", [b["gate"]["name"] for b in blames])
        self.assertTrue(detect.delete_requests(case["reply"]))

    def test_hook_blocks_with_exit_2_and_asks_for_the_rule(self):
        path = transcript_file(REAL["blocked_read"])
        try:
            code, err = run_entry(json.dumps({"last_assistant_message": ACCEPTANCE_REPLY, "transcript_path": path}))
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("gate-blame-needs-evidence", err)
        self.assertIn("cite the rule that fired as file:line", err)
        self.assertIn("A blocked or failed read does not count", err)


class TestSilentWhenTheGateWasReadOrCited(unittest.TestCase):
    def test_silent_when_transcript_holds_read_of_scope_lock_detect(self):
        lines = lines_of(read_of("engine/hooks/scope-lock/detect.py"))
        self.assertIsNone(detect.decide_stop_from_lines(ACCEPTANCE_REPLY, lines, HOOKS_DIR))

    def test_silent_on_every_real_blame_reply_after_the_real_successful_cat(self):
        lines = lines_of(REAL["blocked_read"], REAL["successful_read"])
        for case in REAL["fires"]:
            with self.subTest(line=case["label"]):
                blames = detect.unread_blames(case["reply"], lines, HOOKS_DIR)
                self.assertNotIn("scope-lock", [b["gate"]["name"] for b in blames])

    def test_silent_when_reply_cites_detect_py_line_159(self):
        self.assertIsNone(detect.decide_stop_from_lines(LINE_159_REPLY, [], HOOKS_DIR))
        uncited = LINE_159_REPLY.replace("detect.py line 159", "the detector")
        self.assertIsNotNone(detect.decide_stop_from_lines(uncited, [], HOOKS_DIR))

    def test_silent_on_real_review_unit_reply_after_its_source_was_read(self):
        reply = REAL["silent_after_review_unit_read"]["reply"]
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(REAL["review_unit_read"]), HOOKS_DIR))

    def test_silent_when_user_ran_the_read_themselves(self):
        lines = [{"type": "user", "message": {"role": "user", "content":
                  "<bash-input>cat ~/.claude/hooks/scope-lock/detect.py</bash-input>"}}]
        self.assertIsNone(detect.decide_stop_from_lines(ACCEPTANCE_REPLY, lines, HOOKS_DIR))

    def test_not_flagged_when_claim_is_negated_or_quoted(self):
        for reply in (
            "scope-lock is not broken; it was working as written.",
            'I said "the scope-lock hook is broken" earlier. That was wrong.',
        ):
            with self.subTest(reply=reply):
                self.assertIsNone(detect.decide_stop_from_lines(reply, [], HOOKS_DIR))

    def test_silent_on_unrelated_reply_naming_a_gate(self):
        reply = "Added a fixture for scope-lock and ran its tests: 31 passed."
        self.assertIsNone(detect.decide_stop_from_lines(reply, [], HOOKS_DIR))

    def test_silent_on_blame_with_no_gate_named_anywhere(self):
        self.assertIsNone(detect.decide_stop_from_lines("The nightly build is broken again.", [], HOOKS_DIR))

    def test_silent_when_stop_hook_active(self):
        self.assertIsNone(detect.decide_stop({"last_assistant_message": ACCEPTANCE_REPLY, "stop_hook_active": True}))

    def test_fails_open_on_garbage_stdin(self):
        code, err = run_entry("not json")
        self.assertEqual((code, err), (0, ""))


class TestUncheckedWhenTranscriptCannotBeRead(unittest.TestCase):
    def test_unreadable_transcript_is_unchecked_and_fails_open(self):
        payload = {"last_assistant_message": ACCEPTANCE_REPLY, "transcript_path": "/nonexistent/x.jsonl"}
        outcome, message = detect.check_stop(payload)
        self.assertEqual(outcome, detect.UNCHECKED)
        self.assertIn("could not be read", message)
        code, err = run_entry(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertIn("unchecked", err)

    def test_missing_transcript_path_is_unchecked(self):
        outcome, _ = detect.check_stop({"last_assistant_message": ACCEPTANCE_REPLY})
        self.assertEqual(outcome, detect.UNCHECKED)

    def test_missing_reply_field_is_unchecked(self):
        outcome, message = detect.check_stop({"transcript_path": "/nonexistent/x.jsonl"})
        self.assertEqual(outcome, detect.UNCHECKED)
        self.assertIn("last_assistant_message", message)

    def test_clean_reply_never_opens_the_transcript(self):
        payload = {"last_assistant_message": "Tests pass.", "transcript_path": "/nonexistent/x.jsonl"}
        self.assertEqual(detect.check_stop(payload), (detect.CLEAN, None))

    def test_unlistable_hooks_dir_still_detects_by_path_shape(self):
        err = io.StringIO()
        with redirect_stderr(err):
            message = detect.decide_stop_from_lines(
                "~/.claude/hooks/scope-lock/ still fires after both commands.", [], "/nonexistent/hooks"
            )
        self.assertIn("`scope-lock`", message)
        self.assertIn("cannot list /nonexistent/hooks", err.getvalue())


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
