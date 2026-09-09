#!/usr/bin/env python3
"""Merge agent-routing-guard's Claude PreToolUse (Agent) hook into
~/.claude/settings.json without disturbing any other hook."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.agent.hook.json")
MARKER = "agent-routing-guard/claude_pretooluse_agent.py"


def _is_ours(entry: dict) -> bool:
    return any(MARKER in hook.get("command", "") for hook in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> tuple[dict, bool]:
    entry_list = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    new_entries = fragment["hooks"]["PreToolUse"]
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
        print("ok      claude PreToolUse agent-routing-guard already up to date")
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("link    claude PreToolUse agent-routing-guard merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
