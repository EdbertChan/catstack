#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import judge
from judge_test_base import JudgeTestCase

PY = sys.executable
ON_HIT = "judge hit text"


class PostToolUseTestCase(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.env = dict(os.environ)

    def tearDown(self):
        self.work.cleanup()
        super().tearDown()

    def plant_hit(self):
        judge.write_json_atomic(os.path.join(judge.verdict_dir(self.transcript), "hit.json"), {
            "id": "hit",
            "hook": "demo-hook",
            "transcript": self.transcript,
            "outcome": "hit",
            "on_hit": ON_HIT,
            "reason": "all true: match",
            "finished_at": 1,
        })

    def run_script(self, script, payload):
        return subprocess.run(
            [PY, os.path.join(LIB_DIR, script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
            env=self.env,
        )

    def payload(self):
        return json.dumps({"transcript_path": self.transcript})

    def assert_empty_success(self, result):
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0)

    def assert_bad_json(self, script, harness):
        result = self.run_script(script, "not json")
        self.assert_empty_success(result)
        self.assertIn(harness, result.stderr)


class TestClaudePostToolUse(PostToolUseTestCase):
    script = "claude_post_tool_use.py"
    harness = "Claude PostToolUse"

    def test_hit_is_delivered_as_additional_context_once(self):
        self.plant_hit()
        result = self.run_script(self.script, self.payload())
        self.assert_success(result)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], ON_HIT)
        again = self.run_script(self.script, self.payload())
        self.assert_empty_success(again)
        self.assertEqual(again.stderr, "")

    def test_no_verdict_prints_nothing(self):
        result = self.run_script(self.script, self.payload())
        self.assert_empty_success(result)
        self.assertEqual(result.stderr, "")

    def test_malformed_stdin_exits_zero_with_a_stderr_line(self):
        self.assert_bad_json(self.script, self.harness)


class TestCodexPostToolUse(PostToolUseTestCase):
    script = "codex_post_tool_use.py"
    harness = "Codex PostToolUse"

    def test_hit_is_delivered_as_additional_context_once(self):
        self.plant_hit()
        result = self.run_script(self.script, self.payload())
        self.assert_success(result)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], ON_HIT)
        again = self.run_script(self.script, self.payload())
        self.assert_empty_success(again)
        self.assertEqual(again.stderr, "")

    def test_no_verdict_prints_nothing(self):
        result = self.run_script(self.script, self.payload())
        self.assert_empty_success(result)
        self.assertEqual(result.stderr, "")

    def test_malformed_stdin_exits_zero_with_a_stderr_line(self):
        self.assert_bad_json(self.script, self.harness)


class TestCursorPostToolUse(PostToolUseTestCase):
    script = "cursor_post_tool_use.py"
    harness = "Cursor postToolUse"

    def test_hit_is_delivered_as_additional_context_once(self):
        self.plant_hit()
        result = self.run_script(self.script, self.payload())
        self.assert_success(result)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertEqual(data["additional_context"], ON_HIT)
        again = self.run_script(self.script, self.payload())
        self.assert_empty_success(again)
        self.assertEqual(again.stderr, "")

    def test_no_verdict_prints_nothing(self):
        result = self.run_script(self.script, self.payload())
        self.assert_empty_success(result)
        self.assertEqual(result.stderr, "")

    def test_malformed_stdin_exits_zero_with_a_stderr_line(self):
        self.assert_bad_json(self.script, self.harness)

    def test_conversation_id_without_matching_transcript_exits_zero_with_a_stderr_line(self):
        result = self.run_script(self.script, json.dumps({"conversation_id": "missing"}))
        self.assert_empty_success(result)
        self.assertIn(self.harness, result.stderr)


if __name__ == "__main__":
    unittest.main()
