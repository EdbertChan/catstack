#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

UNRELATED_CLAUDE = {"matcher": "*", "hooks": [{"type": "command", "command": "python3 /opt/other/claude_post.py", "timeout": 3}]}
UNRELATED_CURSOR = {"command": "python3 /opt/other/cursor_post.py", "timeout": 3}
UNRELATED_CODEX = {"matcher": ".*", "hooks": [{"type": "command", "command": "python3 /opt/other/codex_post.py", "timeout": 3}]}


def _nested_commands(entries: list) -> list:
    return [hook.get("command", "") for entry in entries for hook in entry.get("hooks", [])]


def _flat_commands(entries: list) -> list:
    return [str(entry.get("command", "")) for entry in entries]


class InstallerTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, HOME=self.home.name)

    def tearDown(self):
        self.home.cleanup()

    def seed(self, relative: str, data: dict) -> str:
        path = os.path.join(self.home.name, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        return path

    def run_installer(self, script: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [PY, os.path.join(LIB_DIR, script)],
            capture_output=True,
            text=True,
            timeout=10,
            env=self.env,
            cwd=self.home.name,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def run_twice(self, script: str, path: str) -> tuple[str, str, bytes, bytes]:
        first = self.run_installer(script)
        with open(path, "rb") as handle:
            after_first = handle.read()
        second = self.run_installer(script)
        with open(path, "rb") as handle:
            after_second = handle.read()
        return first.stdout, second.stdout, after_first, after_second

    def test_claude_installer_adds_one_post_tool_entry_and_is_idempotent(self):
        path = self.seed(".claude/settings.json", {"hooks": {"PostToolUse": [UNRELATED_CLAUDE]}})
        first, second, after_first, after_second = self.run_twice("install_claude_hook.py", path)
        self.assertIn("link    claude PostToolUse llm-judge", first)
        self.assertIn("link    claude UserPromptSubmit llm-judge", first)
        self.assertIn("ok      claude PostToolUse llm-judge already up to date", second)
        self.assertIn("ok      claude UserPromptSubmit llm-judge already up to date", second)
        self.assertEqual(after_first, after_second)
        hooks = json.loads(after_second)["hooks"]
        post = _nested_commands(hooks["PostToolUse"])
        self.assertEqual(sum("llm-judge/claude_post_tool_use.py" in c for c in post), 1, post)
        self.assertIn("python3 /opt/other/claude_post.py", post)
        prompt = _nested_commands(hooks["UserPromptSubmit"])
        self.assertEqual(sum("llm-judge/claude_prompt_submit.py" in c for c in prompt), 1, prompt)

    def test_cursor_installer_adds_one_post_tool_entry_and_is_idempotent(self):
        path = self.seed(".cursor/hooks.json", {"version": 1, "hooks": {"postToolUse": [UNRELATED_CURSOR]}})
        first, second, after_first, after_second = self.run_twice("install_cursor_hook.py", path)
        self.assertIn("link    cursor postToolUse llm-judge merged", first)
        self.assertIn("ok      cursor postToolUse llm-judge already up to date", second)
        self.assertIn("ok      cursor stop llm-judge already up to date", second)
        self.assertEqual(after_first, after_second)
        hooks = json.loads(after_second)["hooks"]
        post = _flat_commands(hooks["postToolUse"])
        self.assertEqual(sum("llm-judge/cursor_post_tool_use.py" in c for c in post), 1, post)
        self.assertIn("python3 /opt/other/cursor_post.py", post)
        stop = _flat_commands(hooks["stop"])
        self.assertEqual(sum("llm-judge/cursor_session.py" in c for c in stop), 1, stop)

    def test_codex_installer_adds_one_post_tool_entry_and_is_idempotent(self):
        path = self.seed(".codex/hooks.json", {"hooks": {"PostToolUse": [UNRELATED_CODEX]}})
        first, second, after_first, after_second = self.run_twice("install_codex_hook.py", path)
        self.assertIn("link    codex PostToolUse llm-judge merged", first)
        self.assertIn("ok      codex PostToolUse llm-judge already up to date", second)
        self.assertEqual(after_first, after_second)
        post = _nested_commands(json.loads(after_second)["hooks"]["PostToolUse"])
        self.assertEqual(sum("llm-judge/codex_post_tool_use.py" in c for c in post), 1, post)
        self.assertIn("python3 /opt/other/codex_post.py", post)


if __name__ == "__main__":
    unittest.main()
