#!/usr/bin/env python3
"""Only hooks catstack installed can be catstack hooks that went missing.

Another tool registers its own hooks in the same settings file (Invoker puts
one under ~/.invoker/hooks/). Its folder is not in catstack's snapshot, and
never was, so it is not a deleted catstack hook.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detect  # noqa: E402


def settings_with(*commands):
    def load(_path):
        return {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": c} for c in commands]}]}}
    return load


class HookOwnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = self.tmp.name
        self.claude_hooks = os.path.join(home, ".claude", "hooks")
        self.snapshot = os.path.join(home, "snapshots", "v1")
        os.makedirs(os.path.join(self.snapshot, "diu-stop"))
        self.runner = os.path.join(self.claude_hooks, "_runner", "run.py")
        self.invoker = os.path.join(home, ".invoker", "hooks", "invoker-execution", "claude_prompt_submit.mjs")
        patcher = patch.object(detect, "ANCHOR_LINK", os.path.join(self.claude_hooks, "diu-stop"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def deleted(self, *commands):
        return detect.deleted_installed_hooks(
            self.snapshot, settings_path=os.path.join(self.tmp.name, "settings.json"),
            load=settings_with(*commands))

    def test_invoker_hook_outside_the_catstack_root_is_not_a_deleted_hook(self):
        missing, unreadable = self.deleted(
            f"python3 {self.runner} --timeout 9.5 diu-stop/claude_stop_check.py",
            f"node {self.invoker}",
        )
        self.assertIsNone(unreadable)
        self.assertEqual(missing, [])

    def test_catstack_hook_gone_from_the_snapshot_is_still_reported(self):
        missing, _ = self.deleted(
            f"python3 {self.runner} --timeout 9.5 split-scope/claude_prompt_submit.py",
            f"node {self.invoker}",
        )
        self.assertEqual(missing, ["split-scope"])

    def test_direct_path_under_the_catstack_root_is_still_reported(self):
        script = os.path.join(self.claude_hooks, "split-scope", "claude_prompt_submit.py")
        missing, _ = self.deleted(f"python3 {script}")
        self.assertEqual(missing, ["split-scope"])

    def test_installed_folders_never_name_a_foreign_hooks_dir(self):
        names, _ = detect.installed_hook_folders(
            settings_path="unused", load=settings_with(f"node {self.invoker}"))
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
