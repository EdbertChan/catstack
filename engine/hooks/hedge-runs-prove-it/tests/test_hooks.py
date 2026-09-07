#!/usr/bin/env python3
"""Tests for the hedge-runs-prove-it Stop hook.

Run: python3 -m unittest discover -s engine/hooks/hedge-runs-prove-it/tests -v

Fixtures in tests/fixtures/ are sanitized replies from one real session
("presumably moving it to catstack" with no check run) plus the shapes the
rule names. Each fixture carries `verified`: whether the turn ran a
verification tool.
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


def turn_lines(verified):
    lines = [{"type": "user", "message": {"role": "user", "content": "what is this file?"}}]
    if verified:
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status --porcelain"}}]}})
    return lines


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_hook(payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestBlocksUnverifiedHedges(unittest.TestCase):
    def test_blocks_each_hedge_fixture(self):
        for case in load("hedges_fires.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNotNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_hook_blocks_presumably_reply_with_exit_2(self):
        case = load("hedges_fires.json")[0]
        path = transcript_file(turn_lines(False))
        try:
            code, err = run_hook({"last_assistant_message": case["reply"], "transcript_path": path})
        finally:
            os.unlink(path)
        self.assertEqual(code, 2)
        self.assertIn("prove-it", err)
        self.assertIn("presumably", err)

    def test_blocks_unverified_without_reason_even_with_no_transcript(self):
        self.assertIsNotNone(detect.decide({"last_assistant_message": load("hedges_fires.json")[2]["reply"]}))


class TestAllowsVerifiedOrReasonedHedges(unittest.TestCase):
    def test_allows_each_silent_fixture(self):
        for case in load("hedges_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide_from_lines(case["reply"], turn_lines(case["verified"])))

    def test_allows_hedge_when_read_tool_ran_this_turn(self):
        lines = turn_lines(False) + [{"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/x.py"}}]}}]
        self.assertIsNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_verification_was_in_a_previous_turn_only_if_rerun(self):
        lines = turn_lines(True) + [{"type": "user", "message": {"role": "user", "content": "and now?"}}]
        self.assertIsNotNone(detect.decide_from_lines(load("hedges_fires.json")[1]["reply"], lines))

    def test_allows_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"], "stop_hook_active": True,
        }))

    def test_fails_open_on_unreadable_transcript(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": load("hedges_fires.json")[0]["reply"],
            "transcript_path": "/nonexistent/x.jsonl",
        }))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
