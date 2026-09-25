#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

sys.path.insert(0, LIB_DIR)
import install_codex_notify  # noqa: E402

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


class TestComputeCodexNotifyUpdate(unittest.TestCase):
    SCRIPT_PATH = "/home/x/.codex/hooks/llm-judge/codex_notify.py"

    def test_no_notify_line_inserts_before_first_section(self):
        text = 'model = "gpt-5"\n\n[projects."/x"]\ntrust_level = "trusted"\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertIn(f'notify = ["python3", "{self.SCRIPT_PATH}"]', new_text)
        self.assertLess(new_text.index("notify ="), new_text.index("[projects"))
        self.assertIn('model = "gpt-5"', new_text)

    def test_no_notify_line_no_sections_appends(self):
        text = 'model = "gpt-5"\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertTrue(new_text.rstrip("\n").endswith(f'notify = ["python3", "{self.SCRIPT_PATH}"]'))

    def test_existing_unrelated_notify_gets_chained_not_dropped(self):
        text = 'notify = ["/opt/old-notifier", "turn-ended"]\nmodel = "gpt-5"\n'
        new_text, changed, message = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        self.assertIn("chaining 2 prior arg", message)
        new_notify = json.loads(re.search(r"^notify = (\[.*\])$", new_text, re.MULTILINE).group(1))
        self.assertEqual(new_notify, ["python3", self.SCRIPT_PATH, "/opt/old-notifier", "turn-ended"])
        self.assertIn('model = "gpt-5"', new_text)

    def test_already_wired_is_a_noop(self):
        text = f'notify = ["python3", "{self.SCRIPT_PATH}", "/opt/old-notifier"]\n'
        new_text, changed, message = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertFalse(changed)
        self.assertEqual(new_text, text)
        self.assertIn("already wired", message)

    def test_only_the_notify_line_changes(self):
        text = 'a = 1\nnotify = ["/opt/old"]\nb = 2\n'
        new_text, changed, _ = install_codex_notify.compute_notify_update(text, self.SCRIPT_PATH)
        self.assertTrue(changed)
        lines = new_text.splitlines()
        self.assertIn("a = 1", lines)
        self.assertIn("b = 2", lines)

    def test_nested_previous_notify_copy_of_self_collapses_to_one_top_level_entry(self):
        with tempfile.TemporaryDirectory() as home:
            script_path = os.path.join(home, ".codex", "hooks", "llm-judge", "codex_notify.py")
            os.makedirs(os.path.dirname(script_path))
            open(script_path, "w").close()
            nested = json.dumps(["python3", script_path, "/opt/other-notifier", "turn-ended"])
            text = "notify = " + json.dumps(
                ["/opt/other-notifier", "turn-ended", "--previous-notify", nested]
            ) + "\n"
            new_text, changed, _message = install_codex_notify.compute_notify_update(text, script_path)
            self.assertTrue(changed)
            new_notify = json.loads(re.search(r"^notify = (\[.*\])$", new_text, re.MULTILINE).group(1))
            self.assertEqual(new_notify, ["python3", script_path, "/opt/other-notifier", "turn-ended"])
            self.assertNotIn("--previous-notify", new_text)

            second_text, second_changed, _ = install_codex_notify.compute_notify_update(new_text, script_path)
            self.assertFalse(second_changed)
            self.assertEqual(second_text, new_text)

    def test_nested_entry_for_a_different_hook_whose_script_no_longer_exists_is_dropped(self):
        with tempfile.TemporaryDirectory() as home:
            script_path = os.path.join(home, ".codex", "hooks", "llm-judge", "codex_notify.py")
            missing_path = os.path.join(home, "old-checkout", "catstack", "hooks", "diu-stop", "codex_notify.py")
            nested = json.dumps(["python3", missing_path])
            text = "notify = " + json.dumps(
                ["/opt/other-notifier", "--previous-notify", nested]
            ) + "\n"
            new_text, changed, _message = install_codex_notify.compute_notify_update(text, script_path)
            self.assertTrue(changed)
            new_notify = json.loads(re.search(r"^notify = (\[.*\])$", new_text, re.MULTILINE).group(1))
            self.assertEqual(new_notify, ["python3", script_path, "/opt/other-notifier"])
            self.assertNotIn(missing_path, new_text)


if __name__ == "__main__":
    unittest.main()
