#!/usr/bin/env python3
"""Merge pr-schema-gate's Cursor preToolUse hook into ~/.cursor/hooks.json without wiping others.

Reuses claude_pretooluse.py unmodified (same pattern as bug-complaint-leak's
Cursor preToolUse entry): Cursor's preToolUse payload/exit-code contract is
close enough to Claude's that no Cursor-specific script is needed.
"""
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")
MARKER = "pr-schema-gate/claude_pretooluse.py"

FRAGMENT = [
    {
        "matcher": "Bash",
        "command": "python3 $HOME/.cursor/hooks/pr-schema-gate/claude_pretooluse.py",
        "timeout": 5,
    }
]


def _is_ours(entry: dict) -> bool:
    return MARKER in str(entry.get("command", ""))


def load_hooks() -> dict:
    if not os.path.exists(HOOKS_PATH) and not os.path.islink(HOOKS_PATH):
        return {"version": 1, "hooks": {}}
    with open(HOOKS_PATH) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": 1, "hooks": {}}
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    return data


def main() -> None:
    data = load_hooks()
    hooks = data.setdefault("hooks", {})

    existing = list(hooks.get("preToolUse", []))
    kept = [e for e in existing if not _is_ours(e)]
    new_list = kept + FRAGMENT

    if json.dumps(new_list, sort_keys=True) == json.dumps(existing, sort_keys=True):
        print("ok      cursor preToolUse pr-schema-gate already up to date")
        return

    hooks["preToolUse"] = new_list
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("link    cursor preToolUse pr-schema-gate merged")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
