#!/usr/bin/env python3
"""Tests for the gate-blame-needs-evidence Stop hook.

Run: python3 -m unittest discover -s engine/hooks/gate-blame-needs-evidence/tests -v

Fixtures under tests/fixtures/ replay one real Claude Code session in which
a PreToolUse hook (scope-lock) refused every tool call, including every
attempt to read its own source. Each fixture's `reply` is the assistant's
reply copied verbatim; its `transcript` keeps only the tool calls, hook
refusals and hook messages that came before it (successful outputs elided,
home path replaced). Labels are the row numbers the replies were cited by.

  gate_claims_fires.json          line-1879/1882/1939/2056/2081: says the
                                  gate is broken / still fires / clears a
                                  certain way / asks to remove it or delete
                                  its files, with every read refused.
  fewer_than_required_fires.json  line-1769/1826: tells the user to type one
                                  of the two items the refusal requires.
  after_read_silent.json          line-1527: written after the gate's
                                  source was read; stays silent.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402

HOOK_CMD = "python3 $HOME/.claude/hooks/scope-lock/claude_pretool_scope.py"
REFUSAL = (
    "Second scope correction in this session: all tools are stopped. Do not continue the "
    "task or clear this with an apology/restatement. The user must explicitly invoke both "
    "`/reflect` and `automate-me`; then address the drift before resuming."
)
DETECT_SOURCE = (
    'HARD_GATE = (\n'
    '    "Second scope correction in this session: all tools are stopped. Do not continue the "\n'
    '    "task or clear this with an apology/restatement. The user must explicitly invoke both "\n'
    '    "`/reflect` and `automate-me`; then address the drift before resuming."\n'
    ')\n'
)


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def case(name, label):
    return next(c for c in load(name) if c["label"] == label)


def lines_of(events):
    return detect.parse_lines(json.dumps(e) for e in events)


def tool_call(call_id, name, tool_input, output, is_error=False):
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "is_error": is_error, "content": output}]}},
    ]


def refused(call_id, name, tool_input):
    return tool_call(call_id, name, tool_input, f"PreToolUse:{name} hook error: [{HOOK_CMD}]: {REFUSAL}", True)


def read_detect_ok(call_id="ok1"):
    return tool_call(call_id, "Read", {"file_path": "/home/user/.claude/hooks/scope-lock/detect.py"},
                     "   128\t" + DETECT_SOURCE.replace("\n", "\n   129\t"))


def run_entry(payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


def transcript_file(events):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(e) for e in events) + "\n")
    tmp.close()
    return tmp.name


class HomeIsolated(unittest.TestCase):
    """$HOME points at an empty temp dir, so the on-disk lookup of the
    refusal-text file never reads this machine's installed hooks."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        patcher = patch.dict(os.environ, {"HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.home, True)


class TestFiresOnRealReplies(HomeIsolated):
    def test_every_gate_claim_fixture_fires(self):
        for c in load("gate_claims_fires.json"):
            with self.subTest(label=c["label"]):
                message = detect.decide_stop_from_lines(c["reply"], lines_of(c["transcript"]))
                self.assertIsNotNone(message)
                self.assertIn("About `scope-lock`", message)
                self.assertIn("refused", message)

    def test_every_fewer_than_required_fixture_fires(self):
        for c in load("fewer_than_required_fires.json"):
            with self.subTest(label=c["label"]):
                message = detect.decide_stop_from_lines(c["reply"], lines_of(c["transcript"]))
                self.assertIsNotNone(message)
                self.assertIn("names automate-me, reflect as required", message)

    def test_fires_disable_ask_on_line_2081_and_file_delete_on_line_2056(self):
        for label in ("line-2081", "line-2056"):
            with self.subTest(label=label):
                c = case("gate_claims_fires.json", label)
                self.assertTrue(detect.asks_disable(c["reply"]))
                message = detect.decide_stop_from_lines(c["reply"], lines_of(c["transcript"]))
                self.assertIn("asks the user to disable it or delete its files", message)

    def test_hook_blocks_line_2081_with_exit_2(self):
        c = case("gate_claims_fires.json", "line-2081")
        path = transcript_file(c["transcript"])
        try:
            code, err = run_entry({"last_assistant_message": c["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("gate-blame-needs-evidence", err)
        self.assertIn("a refused read is not a read", err)

    def test_refused_read_of_detect_py_counts_as_no_read_and_fires(self):
        events = refused("r1", "Read", {"file_path": "/home/user/.claude/hooks/scope-lock/detect.py"})
        lines = lines_of(events)
        refusals, calls = detect.scan_events(lines)
        gate = detect.build_gates(refusals)["scope-lock"]
        self.assertEqual(detect.read_state(gate, calls), (detect.REFUSED, 1))
        reply = case("gate_claims_fires.json", "line-1939")["reply"]
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines))

    def test_read_of_entrypoint_without_refusal_text_is_no_read_and_fires(self):
        events = refused("r1", "Bash", {"command": "ls"}) + tool_call(
            "ok1", "Read", {"file_path": "/home/user/.claude/hooks/scope-lock/claude_pretool_scope.py"},
            "1\t#!/usr/bin/env python3\n8\tfrom detect import tool_block_reason\n")
        reply = case("gate_claims_fires.json", "line-2081")["reply"]
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines_of(events)))

    def test_refusal_text_seen_outside_the_gate_dir_is_not_a_read_and_fires(self):
        events = refused("r1", "Bash", {"command": "ls"}) + tool_call(
            "ok1", "Bash", {"command": "grep -h 'all tools are stopped' ~/.claude/projects/x/s.jsonl"}, REFUSAL)
        reply = case("gate_claims_fires.json", "line-1879")["reply"]
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines_of(events)))

    def test_quoting_the_refusal_in_the_reply_does_not_exempt_it_and_fires(self):
        reply = case("gate_claims_fires.json", "line-1939")["reply"]
        self.assertIn("Second scope correction in this session: all tools are stopped.", reply)
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines_of(refused("r1", "Bash", {"command": "ls"}))))

    def test_named_hook_with_no_refusal_this_session_fires_until_any_file_is_read(self):
        reply = "The `~/.claude/hooks/no-comments/` hook is broken; its check never matches heredocs."
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, []))
        read = tool_call("ok1", "Read", {"file_path": "/repo/engine/hooks/no-comments/detect.py"}, "1\timport re\n")
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(read)))


class TestSilentAfterARealRead(HomeIsolated):
    def test_line_1527_written_after_the_gate_source_was_read_stays_silent(self):
        for c in load("after_read_silent.json"):
            with self.subTest(label=c["label"]):
                self.assertIsNone(detect.decide_stop_from_lines(c["reply"], lines_of(c["transcript"])))

    def test_every_fire_fixture_is_silent_after_a_successful_read_of_detect_py(self):
        for name in ("gate_claims_fires.json", "fewer_than_required_fires.json"):
            for c in load(name):
                with self.subTest(label=c["label"]):
                    events = c["transcript"] + read_detect_ok()
                    self.assertIsNone(detect.decide_stop_from_lines(c["reply"], lines_of(events)))

    def test_partial_read_of_the_refusal_file_on_disk_counts_as_read_silent(self):
        gate_dir = os.path.join(self.home, ".claude", "hooks", "scope-lock")
        os.makedirs(gate_dir)
        with open(os.path.join(gate_dir, "detect.py"), "w", encoding="utf-8") as handle:
            handle.write(DETECT_SOURCE + "\ndef reflection_invoked(text):\n    return True\n")
        with open(os.path.join(gate_dir, "claude_pretool_scope.py"), "w", encoding="utf-8") as handle:
            handle.write("from detect import tool_block_reason\n")
        events = refused("r1", "Bash", {"command": "ls"}) + tool_call(
            "ok1", "Bash", {"command": "sed -n 7,9p ~/.claude/hooks/scope-lock/detect.py"},
            "def reflection_invoked(text):\n    return True\n")
        reply = case("gate_claims_fires.json", "line-1879")["reply"]
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(events)))
        wrong_file = refused("r1", "Bash", {"command": "ls"}) + tool_call(
            "ok1", "Bash", {"command": "cat ~/.claude/hooks/scope-lock/claude_pretool_scope.py"},
            "from detect import tool_block_reason\n")
        self.assertIsNotNone(detect.decide_stop_from_lines(reply, lines_of(wrong_file)))

    def test_read_state_has_three_outcomes_read_refused_none(self):
        events = refused("r1", "Read", {"file_path": "/home/user/.claude/hooks/scope-lock/detect.py"})
        refusals, calls = detect.scan_events(lines_of(events))
        gate = detect.build_gates(refusals)["scope-lock"]
        self.assertEqual(detect.read_state(gate, calls)[0], detect.REFUSED)
        self.assertEqual(detect.read_state(gate, [])[0], detect.NONE)
        _, calls = detect.scan_events(lines_of(events + read_detect_ok()))
        self.assertEqual(detect.read_state(gate, calls)[0], detect.READ)

    def test_allows_when_stop_hook_active(self):
        c = case("gate_claims_fires.json", "line-2081")
        self.assertEqual(detect.decide_stop({
            "last_assistant_message": c["reply"], "stop_hook_active": True,
        }), (detect.CLEAN, ""))

    def test_unrelated_reply_is_silent(self):
        reply = "Merged #307 and rebased the other five; CI is green on all of them."
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(refused("r1", "Bash", {"command": "ls"}))))

    def test_disable_model_invocation_is_not_a_disable_ask(self):
        self.assertFalse(detect.asks_disable("your corpus has this exact rule for `disable-model-invocation`"))

    def test_steps_listed_in_one_sentence_are_not_fewer_than_required(self):
        reply = "Its message has three steps: you invoke `/reflect`, you invoke `automate-me`, then I resume."
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(refused("r1", "Bash", {"command": "ls"}))))

    def test_quoted_type_instruction_is_not_an_ask(self):
        reply = 'What happened: I handed back a Discord script, `cat`, `ls`, "type `/reflect`" before trying.'
        self.assertIsNone(detect.decide_stop_from_lines(reply, lines_of(refused("r1", "Bash", {"command": "ls"}))))


class TestUncheckedIsNotClean(HomeIsolated):
    def test_unreadable_transcript_is_reported_unchecked_not_clean(self):
        c = case("gate_claims_fires.json", "line-2081")
        payload = {"last_assistant_message": c["reply"], "transcript_path": "/nonexistent/x.jsonl"}
        status, message = detect.decide_stop(payload)
        self.assertEqual(status, detect.UNCHECKED)
        code, err = run_entry(payload)
        self.assertEqual(code, 0)
        self.assertIn("unchecked, not clean", err)

    def test_missing_transcript_path_is_unchecked(self):
        c = case("fewer_than_required_fires.json", "line-1769")
        self.assertEqual(detect.decide_stop({"last_assistant_message": c["reply"]})[0], detect.UNCHECKED)

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


class TestInstall(unittest.TestCase):
    def test_merge_adds_one_stop_entry_and_is_idempotent(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"command": "python3 other.py"}]}]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(sum("gate-blame-needs-evidence/" in c for c in commands), 1)
        self.assertIn("python3 other.py", commands)


if __name__ == "__main__":
    unittest.main()
