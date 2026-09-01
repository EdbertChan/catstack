#!/usr/bin/env python3
"""Merge no-comments's Claude PreToolUse hook into ~/.claude/settings.json without wiping others."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKER = "no-comments/claude_pretooluse.py"


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)

    with open(FRAGMENT_PATH) as f:
        fragment = json.load(f)

    entry_list = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    new_entries = fragment["hooks"]["PreToolUse"]
    before = json.dumps(entry_list, sort_keys=True)
    kept = [e for e in entry_list if not _is_ours(e)]
    entry_list[:] = kept + new_entries
    after = json.dumps(entry_list, sort_keys=True)

    if before == after:
        print("ok      claude PreToolUse no-comments already up to date")
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("link    claude PreToolUse no-comments merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
