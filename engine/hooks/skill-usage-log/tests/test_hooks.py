#!/usr/bin/env python3
"""Unit tests for the skill-usage-log PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/skill-usage-log/tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse_log  # noqa: E402


def run_hook(payload, enabled=True, state_dir=None):
    with patch.object(claude_pretooluse_log, "STATE_DIR", state_dir or ""):
        with patch.dict(
            os.environ,
            {claude_pretooluse_log.ENABLED_ENV: "1" if enabled else "0"},
        ):
            with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                claude_pretooluse_log.main()


def read_lines(state_dir):
    path = os.path.join(state_dir, claude_pretooluse_log.LOG_FILE_NAME)
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


class TestSkillUsageLog(unittest.TestCase):
    def test_enabled_skill_call_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_hook(
                {
                    "tool_name": "Skill",
                    "tool_input": {"skill": "draft-pr", "args": "foo"},
                    "session_id": "sess-1",
                    "cwd": "/repo",
                },
                enabled=True,
                state_dir=tmp,
            )
            lines = read_lines(tmp)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["skill"], "draft-pr")
            self.assertEqual(lines[0]["args"], "foo")
            self.assertEqual(lines[0]["session_id"], "sess-1")
            self.assertEqual(lines[0]["cwd"], "/repo")
            self.assertIn("ts", lines[0])

    def test_disabled_flag_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_hook(
                {"tool_name": "Skill", "tool_input": {"skill": "draft-pr"}},
                enabled=False,
                state_dir=tmp,
            )
            self.assertEqual(read_lines(tmp), [])
            self.assertFalse(os.path.exists(claude_pretooluse_log.log_path()))

    def test_missing_skill_name_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_hook(
                {"tool_name": "Skill", "tool_input": {}},
                enabled=True,
                state_dir=tmp,
            )
            self.assertEqual(read_lines(tmp), [])

    def test_malformed_stdin_json_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(claude_pretooluse_log, "STATE_DIR", tmp):
                with patch.dict(os.environ, {claude_pretooluse_log.ENABLED_ENV: "1"}):
                    with patch.object(sys, "stdin", io.StringIO("not json")):
                        claude_pretooluse_log.main()
            self.assertEqual(read_lines(tmp), [])

    def test_non_dict_payload_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_hook(["not", "a", "dict"], enabled=True, state_dir=tmp)
            self.assertEqual(read_lines(tmp), [])

    def test_two_calls_append_two_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_hook({"tool_input": {"skill": "a"}}, enabled=True, state_dir=tmp)
            run_hook({"tool_input": {"skill": "b"}}, enabled=True, state_dir=tmp)
            lines = read_lines(tmp)
            self.assertEqual([entry["skill"] for entry in lines], ["a", "b"])

    def test_unwritable_state_dir_fails_open(self):
        with patch.object(claude_pretooluse_log, "STATE_DIR", "/nonexistent-root/nope"):
            with patch("os.makedirs", side_effect=OSError("no permission")):
                with patch.object(
                    sys, "stdin", io.StringIO(json.dumps({"tool_input": {"skill": "x"}}))
                ):
                    with patch.dict(os.environ, {claude_pretooluse_log.ENABLED_ENV: "1"}):
                        claude_pretooluse_log.main()


if __name__ == "__main__":
    unittest.main()
