#!/usr/bin/env python3
"""Tests for the agent-relay-attribution advisory Stop hook.

Run: python3 -m unittest discover -s engine/hooks/agent-relay-attribution/tests -v

Fixtures are sanitized replies from one real session: the ones that relayed
a subagent's "187 tests passing" / "Ran 185 tests ... OK" as bare fact
(fires) and the ones that said "Per the agent's report" or re-ran the suite
(silent). Each carries the one-turn transcript it was sent in.
"""
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
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_hook(payload):
    err, out = io.StringIO(), io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err), redirect_stdout(out):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue(), out.getvalue()
    return 0, err.getvalue(), out.getvalue()


class TestFlagsUnattributedRelays(unittest.TestCase):
    def test_flags_each_fires_fixture(self):
        for case in load("relay_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(detect.decide_from_lines(case["reply"], case["transcript"]))

    def test_hook_is_advisory_exit_0_with_system_message(self):
        case = load("relay_fires.json")[0]
        path = transcript_file(case["transcript"])
        try:
            code, err, out = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertIn("agent-relay-attribution", err)
        self.assertIn("attribute relayed claims or re-verify", json.loads(out)["systemMessage"])


class TestStaysSilentWhenAttributedOrVerified(unittest.TestCase):
    def test_silent_on_each_silent_fixture(self):
        for case in load("relay_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide_from_lines(case["reply"], case["transcript"]))

    def test_silent_when_stop_hook_active(self):
        case = load("relay_fires.json")[0]
        self.assertIsNone(detect.decide({"last_assistant_message": case["reply"], "stop_hook_active": True}))

    def test_silent_without_transcript_or_on_unreadable_transcript(self):
        case = load("relay_fires.json")[0]
        self.assertIsNone(detect.decide({"last_assistant_message": case["reply"]}))
        self.assertIsNone(detect.decide({
            "last_assistant_message": case["reply"], "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err, out = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err), redirect_stdout(out):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
