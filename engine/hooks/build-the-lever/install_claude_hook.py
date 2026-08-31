#!/usr/bin/env python3
"""Merge build-the-lever Claude hooks into ~/.claude/settings.json without wiping others."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

HOOK_SPECS = [
    ("UserPromptSubmit", "build-the-lever/claude_prompt_submit.py", os.path.join(HERE, "claude.prompt.hook.json")),
    ("PostToolUse", "build-the-lever/claude_posttooluse.py", os.path.join(HERE, "claude.tool.hook.json")),
]


def _is_ours(entry: dict, marker: str) -> bool:
    return any(marker in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook_type(settings: dict, hook_type: str, marker: str, fragment: dict) -> bool:
    entry_list = settings.setdefault("hooks", {}).setdefault(hook_type, [])
    new_entries = fragment.get("hooks", {}).get(hook_type, [])
    before = json.dumps(entry_list, sort_keys=True)
    kept = [e for e in entry_list if not _is_ours(e, marker)]
    entry_list[:] = kept + new_entries
    return json.dumps(entry_list, sort_keys=True) != before


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as handle:
            settings = json.load(handle)

    any_changed = False
    loaded: dict[str, dict] = {}
    for hook_type, marker, fragment_path in HOOK_SPECS:
        if fragment_path not in loaded:
            with open(fragment_path) as handle:
                loaded[fragment_path] = json.load(handle)
        fragment = loaded[fragment_path]
        if merge_hook_type(settings, hook_type, marker, fragment):
            any_changed = True
            print(f"link    claude {hook_type} build-the-lever merged")
        else:
            print(f"ok      claude {hook_type} build-the-lever already up to date")

    if not any_changed:
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
