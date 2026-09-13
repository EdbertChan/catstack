#!/usr/bin/env python3
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKER = "handback-needs-attempt/claude_stop_check.py"
EVENT = "Stop"


def _is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict) -> bool:
    entries = settings.setdefault("hooks", {}).setdefault(EVENT, [])
    incoming = fragment.get("hooks", {}).get(EVENT, [])
    before = json.dumps(entries, sort_keys=True)
    entries[:] = [entry for entry in entries if not _is_ours(entry)] + incoming
    return json.dumps(entries, sort_keys=True) != before


def main() -> None:
    settings = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)
    if not merge_hook(settings, fragment):
        print("ok      claude Stop handback-needs-attempt already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("link    claude Stop handback-needs-attempt merged into settings.json")
