#!/usr/bin/env python3
"""Idempotently merge diu-stop's Claude Code hooks into ~/.claude/settings.json:
the Stop hook (reactive -- catches a long/unverified response after it's
written) and the UserPromptSubmit hook (proactive -- reminds the model of
diu's rules before it writes).

Safe to rerun on every `install.sh`: each hook type is identified by whether
any of its entries' "command" mentions that hook's own marker script,
replaces just that hook type's diu-stop entry with the current fragment
file's content, and leaves every other key in settings.json (model, theme,
other hooks, other hook types, ...) untouched. That means editing either
fragment file and rerunning install.sh converges cleanly instead of
appending a duplicate entry each time.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

# (hook type in settings.json, marker script identifying "our" entry, fragment file)
HOOK_SPECS = [
    ("Stop", "claude_stop_check.py", os.path.join(HERE, "claude.hook.json")),
    ("UserPromptSubmit", "claude_prompt_reminder.py", os.path.join(HERE, "claude.prompt.hook.json")),
]


def _is_ours(entry, marker):
    return any(marker in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings, hook_type, marker, fragment):
    """Pure: returns (new_settings, changed). Replaces any existing
    diu-stop entry of this hook type with fragment's, appends if none
    existed yet."""
    settings = json.loads(json.dumps(settings))  # deep copy, no external dep
    entry_list = settings.setdefault("hooks", {}).setdefault(hook_type, [])
    new_entries = fragment["hooks"][hook_type]

    before = json.dumps(entry_list, sort_keys=True)
    entry_list[:] = [e for e in entry_list if not _is_ours(e, marker)] + new_entries
    changed = json.dumps(entry_list, sort_keys=True) != before
    return settings, changed


def main():
    settings = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)

    any_changed = False
    for hook_type, marker, fragment_path in HOOK_SPECS:
        with open(fragment_path) as f:
            fragment = json.load(f)
        settings, changed = merge_hook(settings, hook_type, marker, fragment)
        if changed:
            any_changed = True
            print(f"link    claude {hook_type} hook merged into settings.json")
        else:
            print(f"ok      claude {hook_type} hook already up to date")

    if not any_changed:
        return

    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
