#!/usr/bin/env python3
"""Unit tests for scripts/mirror_stop_hooks_to_subagent_stop.py: the pure
mirror() over synthetic settings, and load_manifests() over both a throwaway
hooks dir and the real engine/hooks tree. Never touches ~/.claude.

Run: python3 -m unittest tests.test_mirror_subagent_stop -v
"""
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import mirror_stop_hooks_to_subagent_stop as mod  # noqa: E402

OPTED_OUT_ON_MAIN = {"frustration-watchdog", "auto-pr", "unverified-tag-ledger"}


def stop_entry(name: str, script: str = "claude_stop_check.py") -> dict:
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": f"python3 $HOME/.claude/hooks/{name}/{script}", "timeout": 10}],
    }


def write_manifest(hooks_dir: str, name: str, body: dict, filename: str = "claude.hook.json") -> str:
    path = os.path.join(hooks_dir, name, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle)
    return path


def commands(settings: dict, event: str) -> list[str]:
    return [h["command"] for e in settings.get("hooks", {}).get(event, []) for h in e["hooks"]]


class TestLoadManifests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hooks_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_manifests_that_wire_stop_are_returned(self):
        write_manifest(self.hooks_dir, "stopper", {"hooks": {"Stop": [stop_entry("stopper")]}})
        write_manifest(self.hooks_dir, "pretool", {"hooks": {"PreToolUse": [stop_entry("pretool")]}})
        write_manifest(self.hooks_dir, "prompt-only", {"hooks": {"UserPromptSubmit": [stop_entry("prompt-only")]}}, "claude.prompt.hook.json")
        names = [m.name for m in mod.load_manifests(self.hooks_dir)]
        self.assertEqual(names, ["stopper"])

    def test_opt_out_with_reason_is_recorded(self):
        write_manifest(self.hooks_dir, "quiet", {
            "hooks": {"Stop": [stop_entry("quiet")]},
            "subagent_stop": {"inherit": False, "reason": "talks to the human only"},
        })
        [manifest] = mod.load_manifests(self.hooks_dir)
        self.assertFalse(manifest.inherit)
        self.assertEqual(manifest.reason, "talks to the human only")

    def test_opt_out_without_reason_is_rejected(self):
        write_manifest(self.hooks_dir, "silent", {
            "hooks": {"Stop": [stop_entry("silent")]},
            "subagent_stop": {"inherit": False},
        })
        with self.assertRaises(ValueError):
            mod.load_manifests(self.hooks_dir)

    def test_real_repo_every_stop_hook_inherits_or_names_a_reason(self):
        manifests = mod.load_manifests()
        self.assertTrue(manifests)
        for manifest in manifests:
            with self.subTest(hook=manifest.name):
                self.assertTrue(manifest.inherit or manifest.reason, manifest.path)

    def test_real_repo_opted_out_set_is_the_documented_one(self):
        opted_out = {m.name for m in mod.load_manifests() if not m.inherit}
        self.assertEqual(opted_out, OPTED_OUT_ON_MAIN)


class TestMirror(unittest.TestCase):
    def manifests(self):
        return [
            mod.StopManifest(name="a", path="a", entries=[stop_entry("a")]),
            mod.StopManifest(name="b", path="b", entries=[stop_entry("b", "claude_stop_b.py")]),
            mod.StopManifest(name="quiet", path="quiet", entries=[stop_entry("quiet")], inherit=False, reason="human only"),
        ]

    def test_every_inheriting_stop_hook_gets_a_subagent_stop_entry_without_matcher(self):
        out, changed = mod.mirror({"hooks": {}}, self.manifests())
        self.assertTrue(changed)
        self.assertEqual(commands(out, "SubagentStop"), [
            "python3 $HOME/.claude/hooks/a/claude_stop_check.py",
            "python3 $HOME/.claude/hooks/b/claude_stop_b.py",
        ])
        for entry in out["hooks"]["SubagentStop"]:
            self.assertNotIn("matcher", entry)

    def test_opted_out_hook_is_not_mirrored_and_a_stale_mirror_is_removed(self):
        stale = {"hooks": {"SubagentStop": [stop_entry("quiet")]}}
        out, changed = mod.mirror(stale, self.manifests())
        self.assertTrue(changed)
        self.assertNotIn("python3 $HOME/.claude/hooks/quiet/claude_stop_check.py", commands(out, "SubagentStop"))

    def test_foreign_subagent_stop_entries_and_other_keys_survive(self):
        foreign = {"hooks": [{"type": "command", "command": "node /x/.invoker/hooks/y/claude_subagent_stop.mjs"}]}
        settings = {"model": "sonnet", "hooks": {"SubagentStop": [foreign], "Stop": [stop_entry("a")]}}
        out, _ = mod.mirror(settings, self.manifests())
        self.assertEqual(out["model"], "sonnet")
        self.assertEqual(commands(out, "Stop"), ["python3 $HOME/.claude/hooks/a/claude_stop_check.py"])
        self.assertIn("node /x/.invoker/hooks/y/claude_subagent_stop.mjs", commands(out, "SubagentStop"))

    def test_rerun_is_idempotent(self):
        first, _ = mod.mirror({"hooks": {}}, self.manifests())
        second, changed = mod.mirror(first, self.manifests())
        self.assertFalse(changed)
        self.assertEqual(first, second)

    def test_empty_result_does_not_leave_an_empty_event_key(self):
        out, changed = mod.mirror({"hooks": {}}, [])
        self.assertFalse(changed)
        self.assertNotIn("SubagentStop", out["hooks"])


if __name__ == "__main__":
    unittest.main()
