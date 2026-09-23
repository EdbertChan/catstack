from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(REPO_DIR, "scripts", "install"))

import install_claude_hook
import mirror_stop_hooks_to_subagent_stop


class TestInstall(unittest.TestCase):
    def test_manifest_has_stop_entry(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        commands = [hook["command"] for entry in manifest["hooks"]["Stop"] for hook in entry["hooks"]]
        self.assertEqual(len(commands), 1)
        self.assertIn("handback-needs-attempt/claude_stop_check.py", commands[0])

    def test_installer_merges_one_stop_entry_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            settings_path = os.path.join(temp, "settings.json")
            with open(settings_path, "w", encoding="utf-8") as handle:
                json.dump({"hooks": {"Stop": [{"matcher": "*", "hooks": [{"command": "other"}]}]}}, handle)
            with patch.object(install_claude_hook, "SETTINGS_PATH", settings_path):
                with redirect_stdout(StringIO()):
                    install_claude_hook.main()
                with redirect_stdout(StringIO()):
                    install_claude_hook.main()
            with open(settings_path, encoding="utf-8") as handle:
                settings = json.load(handle)
        commands = [hook.get("command", "") for entry in settings["hooks"]["Stop"] for hook in entry["hooks"]]
        self.assertEqual(sum("handback-needs-attempt/claude_stop_check.py" in command for command in commands), 1)
        self.assertIn("other", commands)

    def test_stop_entry_is_mirrored_to_subagent_stop(self):
        manifest_path = os.path.join(HOOK_DIR, "claude.hook.json")
        with open(manifest_path, encoding="utf-8") as handle:
            entries = json.load(handle)["hooks"]["Stop"]
        manifests = [mirror_stop_hooks_to_subagent_stop.StopManifest(
            name="handback-needs-attempt", path=manifest_path, entries=entries,
        )]
        settings, changed = mirror_stop_hooks_to_subagent_stop.mirror({}, manifests)
        self.assertTrue(changed)
        commands = [hook["command"] for entry in settings["hooks"]["SubagentStop"] for hook in entry["hooks"]]
        self.assertEqual(len(commands), 1)
        self.assertIn("handback-needs-attempt/claude_stop_check.py", commands[0])

    def test_install_sh_links_and_merges_the_hook(self):
        with open(os.path.join(REPO_DIR, "install.sh"), encoding="utf-8") as handle:
            install = handle.read()
        self.assertIn('link_item "handback-needs-attempt" "$REPO_DIR/engine/hooks/handback-needs-attempt" "$HOME/.claude/hooks/handback-needs-attempt"', install)
        self.assertIn('python3 "$REPO_DIR/engine/hooks/handback-needs-attempt/install_claude_hook.py"', install)


if __name__ == "__main__":
    unittest.main()
