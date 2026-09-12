#!/usr/bin/env python3
"""Merge split-scope Claude hooks into ~/.claude/settings.json without wiping others."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
HOOK_TYPE = "UserPromptSubmit"
MARKER = "split-scope/claude_prompt_submit.py"
FRAGMENT_PATH = os.path.join(HERE, "claude.prompt.hook.json")


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook_type(settings: dict, fragment: dict) -> bool:
    entry_list = settings.setdefault("hooks", {}).setdefault(HOOK_TYPE, [])
    new_entries = fragment.get("hooks", {}).get(HOOK_TYPE, [])
    before = json.dumps(entry_list, sort_keys=True)
    kept = [entry for entry in entry_list if not _is_ours(entry)]
    entry_list[:] = kept + new_entries
    return json.dumps(entry_list, sort_keys=True) != before


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)
    if not merge_hook_type(settings, fragment):
        print("ok      claude UserPromptSubmit split-scope already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("link    claude UserPromptSubmit split-scope merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
