#!/usr/bin/env python3
"""Idempotently merge diu-stop's Stop hook into ~/.claude/settings.json.

Safe to rerun on every `install.sh`: identifies "our" entry by whether any
of its hooks' "command" mentions claude_stop_check.py, replaces just that
entry with the current hooks/diu-stop/claude.hook.json content, and leaves
every other key in settings.json (model, theme, other hooks, ...) untouched.
That means editing claude.hook.json and rerunning install.sh converges
cleanly instead of appending a duplicate entry each time.
"""
import json
import os

MARKER = "claude_stop_check.py"
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude.hook.json")


def _is_ours(stop_entry):
    return any(MARKER in h.get("command", "") for h in stop_entry.get("hooks", []))


def merge_stop_hook(settings, fragment):
    """Pure: returns (new_settings, changed). Replaces any existing
    diu-stop Stop entry with fragment's, appends if none existed yet."""
    settings = json.loads(json.dumps(settings))  # deep copy, no external dep
    stop_list = settings.setdefault("hooks", {}).setdefault("Stop", [])
    new_entries = fragment["hooks"]["Stop"]

    before = json.dumps(stop_list, sort_keys=True)
    stop_list[:] = [e for e in stop_list if not _is_ours(e)] + new_entries
    changed = json.dumps(stop_list, sort_keys=True) != before
    return settings, changed


def main():
    settings = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)

    with open(FRAGMENT_PATH) as f:
        fragment = json.load(f)

    new_settings, changed = merge_stop_hook(settings, fragment)
    if not changed:
        print("ok      claude Stop hook already up to date")
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(new_settings, f, indent=2)
        f.write("\n")
    print("link    claude Stop hook merged into settings.json (restart Claude Code to pick it up)")


if __name__ == "__main__":
    main()
