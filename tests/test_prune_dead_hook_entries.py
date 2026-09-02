#!/usr/bin/env python3
"""Unit tests for scripts/prune_dead_hook_entries.py against synthetic
settings dictionaries and a fake ``exists`` predicate. Never touches the real
~/.claude/settings.json.

Run: python3 -m unittest tests.test_prune_dead_hook_entries -v
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import prune_dead_hook_entries as mod  # noqa: E402

HOME = "/fake/home"
LIVE = "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py"
DEAD = "python3 $HOME/.claude/hooks/ghost/claude_posttooluse.py"
OUTSIDE = "node /fake/home/.invoker/hooks/x/claude_prompt_submit.mjs"


def exists_only(*live_suffixes):
    def _exists(path):
        return any(path.endswith(s) for s in live_suffixes)
    return _exists


def settings_with(*commands, extra=None):
    groups = [{"matcher": "", "hooks": [{"type": "command", "command": c} for c in commands]}]
    base = {"hooks": {"PostToolUse": groups}}
    base.update(extra or {})
    return base


class TestPrune(unittest.TestCase):
    def test_dead_entry_is_removed_and_live_entry_kept(self):
        settings = settings_with(LIVE, DEAD)
        out, removed = mod.prune(settings, exists_only("diu-stop/claude_stop_check.py"), home=HOME)
        commands = [h["command"] for g in out["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertEqual(commands, [LIVE])
        self.assertEqual(len(removed), 1)
        self.assertIn("ghost", removed[0])

    def test_entry_outside_hooks_dir_kept_even_if_missing(self):
        settings = settings_with(OUTSIDE)
        out, removed = mod.prune(settings, lambda p: False, home=HOME)
        commands = [h["command"] for g in out["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertEqual(commands, [OUTSIDE])
        self.assertEqual(removed, [])

    def test_emptied_matcher_group_is_dropped(self):
        settings = settings_with(DEAD)
        out, removed = mod.prune(settings, lambda p: False, home=HOME)
        self.assertEqual(out["hooks"]["PostToolUse"], [])
        self.assertEqual(len(removed), 1)

    def test_unrelated_keys_and_events_survive(self):
        settings = settings_with(DEAD, extra={"model": "sonnet", "permissions": {"allow": ["Bash"]}})
        settings["hooks"]["Stop"] = [{"matcher": "", "hooks": [{"type": "command", "command": LIVE}]}]
        out, _ = mod.prune(settings, exists_only("claude_stop_check.py"), home=HOME)
        self.assertEqual(out["model"], "sonnet")
        self.assertEqual(out["permissions"], {"allow": ["Bash"]})
        self.assertEqual(out["hooks"]["Stop"][0]["hooks"][0]["command"], LIVE)

    def test_expanded_home_path_is_also_recognised(self):
        expanded = f"python3 {HOME}/.claude/hooks/ghost/x.py"
        settings = settings_with(expanded)
        out, removed = mod.prune(settings, lambda p: False, home=HOME)
        self.assertEqual(out["hooks"]["PostToolUse"], [])
        self.assertEqual(len(removed), 1)

    def test_input_is_not_mutated(self):
        settings = settings_with(DEAD)
        before = str(settings)
        mod.prune(settings, lambda p: False, home=HOME)
        self.assertEqual(str(settings), before)

    def test_no_hooks_key_is_a_noop(self):
        out, removed = mod.prune({"model": "sonnet"}, lambda p: False, home=HOME)
        self.assertEqual(out, {"model": "sonnet"})
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
