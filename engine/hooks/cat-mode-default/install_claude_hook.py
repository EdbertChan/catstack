#!/usr/bin/env python3
"""Merge the cat-mode-default UserPromptSubmit hook into ~/.claude/settings.json
without touching any other entry. Idempotent: reruns replace only the entry
whose command names this hook's script."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
MARKER = "cat-mode-default/claude_prompt_submit.py"
FRAGMENT_PATH = os.path.join(HERE, "claude.prompt.hook.json")
HOOK_TYPE = "UserPromptSubmit"


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> tuple[dict, bool]:
    settings = json.loads(json.dumps(settings))
    entry_list = settings.setdefault("hooks", {}).setdefault(HOOK_TYPE, [])
    new_entries = fragment["hooks"][HOOK_TYPE]
    before = json.dumps(entry_list, sort_keys=True)
    entry_list[:] = [e for e in entry_list if not _is_ours(e)] + new_entries
    return settings, json.dumps(entry_list, sort_keys=True) != before


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as handle:
            settings = json.load(handle)
    with open(FRAGMENT_PATH) as handle:
        fragment = json.load(handle)
    settings, changed = merge_hook(settings, fragment)
    if not changed:
        print(f"ok      claude {HOOK_TYPE} cat-mode-default already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print(f"link    claude {HOOK_TYPE} cat-mode-default merged into settings.json")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
