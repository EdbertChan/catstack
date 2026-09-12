#!/usr/bin/env python3
"""Merge publish-act-guard's Claude PreToolUse (Bash) hook into
~/.claude/settings.json, and drop the retired agent-routing-guard entry it
replaces, without disturbing any other hook."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKER = "publish-act-guard/claude_pretooluse.py"
RETIRED_MARKER = "agent-routing-guard/claude_pretooluse_agent.py"


def _has_marker(entry: dict, marker: str) -> bool:
    return any(marker in hook.get("command", "") for hook in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> tuple[dict, bool]:
    entry_list = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    new_entries = fragment["hooks"]["PreToolUse"]
    before = json.dumps(entry_list, sort_keys=True)
    kept = [
        entry
        for entry in entry_list
        if not _has_marker(entry, MARKER) and not _has_marker(entry, RETIRED_MARKER)
    ]
    entry_list[:] = kept + new_entries
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
        print("ok      claude PreToolUse publish-act-guard already up to date")
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("link    claude PreToolUse publish-act-guard merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
