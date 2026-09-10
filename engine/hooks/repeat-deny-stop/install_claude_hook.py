#!/usr/bin/env python3
"""Merge repeat-deny-stop into ~/.claude/settings.json (PostToolBatch).
Idempotent."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKER = "repeat-deny-stop/"
EVENTS = ("PostToolBatch",)


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> bool:
    changed = False
    for event in EVENTS:
        entry_list = settings.setdefault("hooks", {}).setdefault(event, [])
        new_entries = fragment.get("hooks", {}).get(event, [])
        before = json.dumps(entry_list, sort_keys=True)
        kept = [e for e in entry_list if not _is_ours(e)]
        entry_list[:] = kept + new_entries
        changed = changed or json.dumps(entry_list, sort_keys=True) != before
    return changed


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as handle:
            settings = json.load(handle)
    with open(FRAGMENT_PATH) as handle:
        fragment = json.load(handle)
    if not merge_hook(settings, fragment):
        print("ok      claude PostToolBatch repeat-deny-stop already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("added   claude PostToolBatch repeat-deny-stop")


if __name__ == "__main__":
    main()
