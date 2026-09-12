#!/usr/bin/env python3
"""Tests for the handoff-needs-smoke-test Stop hook.

Run: python3 -m unittest discover -s engine/hooks/handoff-needs-smoke-test/tests -v

The first positive fixture is the verbatim reply that handed over a login
script whose remote half had collapsed into one line. Eight other Stop
hooks saw that reply and passed it.
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
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def turn_lines(ran):
    lines = [{"type": "user", "message": {"role": "user", "content": "set that up for me"}}]
    for script in ran:
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": f"bash /private/tmp/claude-501/scratchpad/{script}"}}]}})
    return lines


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


class TestBlocksUntestedHandoffs(unittest.TestCase):
    def test_hit_every_fires_fixture(self):
        for case in load("handoffs_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["ran"]))
                )

    def test_hit_names_only_the_script_that_never_ran(self):
        case = load("handoffs_fires.json")[2]
        message = detect.decide_from_lines(case["reply"], turn_lines(case["ran"]))
        self.assertIn("stage-two.sh", message)
        self.assertNotIn("stage-one.sh", message)

    def test_hit_exit_code_is_2_with_the_escape_named(self):
        case = load("handoffs_fires.json")[0]
        path = transcript_file(turn_lines([]))
        err = io.StringIO()
        try:
            with patch.object(sys, "stdin", io.StringIO(json.dumps(
                {"last_assistant_message": case["reply"], "transcript_path": path}
            ))):
                with redirect_stderr(err):
                    try:
                        claude_stop_check.main()
                        code = 0
                    except SystemExit as exc:
                        code = exc.code
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("harmless payload", err.getvalue())
        self.assertIn("name the blocker", err.getvalue())

    def test_hit_writing_the_script_is_not_running_it(self):
        lines = [{"type": "user", "message": {"role": "user", "content": "set it up"}},
                 {"type": "assistant", "message": {"role": "assistant", "content": [
                     {"type": "tool_use", "id": "t1", "name": "Bash", "input": {
                         "command": "cat > /tmp/demo-login.sh <<'EOF'\necho hi\nEOF\nchmod +x /tmp/demo-login.sh"}}]}}]
        self.assertIsNotNone(
            detect.decide_from_lines("! bash /tmp/demo-login.sh", lines)
        )


class TestAllowsEverythingElse(unittest.TestCase):
    def test_no_hit_every_silent_fixture(self):
        for case in load("handoffs_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(
                    detect.decide_from_lines(case["reply"], turn_lines(case["ran"]))
                )

    def test_no_hit_when_stop_hook_active(self):
        case = load("handoffs_fires.json")[0]
        self.assertIsNone(detect.decide({
            "last_assistant_message": case["reply"], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        case = load("handoffs_fires.json")[0]
        self.assertIsNone(detect.decide({
            "last_assistant_message": case["reply"],
            "transcript_path": "/nonexistent/session.jsonl",
        }))

    def test_fails_open_on_missing_transcript_path(self):
        case = load("handoffs_fires.json")[0]
        self.assertIsNone(detect.decide({"last_assistant_message": case["reply"]}))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")

    def test_no_hit_on_a_reply_with_no_handoff_at_all(self):
        self.assertIsNone(detect.decide_from_lines(
            "The deploy is done and the owner is healthy.", turn_lines([])))


if __name__ == "__main__":
    unittest.main()
