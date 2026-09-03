#!/usr/bin/env python3
"""Merge skill-usage-log into ~/.claude/settings.json PreToolUse hooks. Idempotent."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKER = "skill-usage-log/claude_pretooluse_log.py"
EVENT = "PreToolUse"


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> bool:
    entry_list = settings.setdefault("hooks", {}).setdefault(EVENT, [])
    new_entries = fragment.get("hooks", {}).get(EVENT, [])
    before = json.dumps(entry_list, sort_keys=True)
    kept = [e for e in entry_list if not _is_ours(e)]
    entry_list[:] = kept + new_entries
    return json.dumps(entry_list, sort_keys=True) != before


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as handle:
            settings = json.load(handle)
    with open(FRAGMENT_PATH) as handle:
        fragment = json.load(handle)
    if not merge_hook(settings, fragment):
        print("ok      claude PreToolUse skill-usage-log already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("added   claude PreToolUse skill-usage-log")


if __name__ == "__main__":
    main()
