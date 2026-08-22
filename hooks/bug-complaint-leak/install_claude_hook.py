#!/usr/bin/env python3
"""Merge bug-complaint-leak Claude hooks into ~/.claude/settings.json without wiping others."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

HOOK_SPECS = [
    ("UserPromptSubmit", "bug-complaint-leak/claude_prompt_submit.py", os.path.join(HERE, "claude.prompt.hook.json")),
    ("PreToolUse", "bug-complaint-leak/claude_pretooluse_grep.py", os.path.join(HERE, "claude.tool.hook.json")),
    ("PostToolUse", "bug-complaint-leak/claude_posttooluse.py", os.path.join(HERE, "claude.tool.hook.json")),
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
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)

    any_changed = False
    # Load fragments once; PreToolUse and PostToolUse share claude.tool.hook.json
    loaded: dict[str, dict] = {}
    for hook_type, marker, fragment_path in HOOK_SPECS:
        if fragment_path not in loaded:
            with open(fragment_path) as f:
                loaded[fragment_path] = json.load(f)
        fragment = loaded[fragment_path]
        if merge_hook_type(settings, hook_type, marker, fragment):
            any_changed = True
            print(f"link    claude {hook_type} bug-complaint-leak merged")
        else:
            print(f"ok      claude {hook_type} bug-complaint-leak already up to date")

    if not any_changed:
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
