from __future__ import annotations

import json
import os
import sys
import unittest

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import install_claude_hook


class TestInstall(unittest.TestCase):
    def fragment(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            return json.load(handle)

    def test_merge_preserves_unrelated_stop_entries_and_is_idempotent(self):
        fragment = self.fragment()
        unrelated = {"matcher": "other", "hooks": [{"type": "command", "command": "other"}]}
        settings = {"hooks": {"Stop": [unrelated]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        self.assertEqual(settings["hooks"]["Stop"][0], unrelated)
        commands = [
            hook["command"]
            for entry in settings["hooks"]["Stop"]
            for hook in entry.get("hooks", [])
        ]
        self.assertEqual(
            commands.count("python3 $HOME/.claude/hooks/handback-needs-attempt/claude_stop_check.py"),
            1,
        )

    def test_manifest_declares_stop_command(self):
        fragment = self.fragment()
        commands = [
            hook["command"]
            for entry in fragment["hooks"]["Stop"]
            for hook in entry.get("hooks", [])
        ]
        self.assertEqual(
            commands,
            ["python3 $HOME/.claude/hooks/handback-needs-attempt/claude_stop_check.py"],
        )

    def test_install_script_links_and_merges_hook(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
        with open(os.path.join(root, "install.sh"), encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn(
            'link_item "handback-needs-attempt" "$REPO_DIR/engine/hooks/handback-needs-attempt" "$HOME/.claude/hooks/handback-needs-attempt"',
            script,
        )
        self.assertIn(
            'python3 "$REPO_DIR/engine/hooks/handback-needs-attempt/install_claude_hook.py"',
            script,
        )


if __name__ == "__main__":
    unittest.main()
