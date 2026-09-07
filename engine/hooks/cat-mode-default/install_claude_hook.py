#!/usr/bin/env python3
"""Merge cat-mode-default's two Claude hooks into ~/.claude/settings.json
without touching any other entry: the UserPromptSubmit hook (the user's own
turns) and the PreToolUse hook on the Agent tool (subagent prompts).
Idempotent: reruns replace only the entry whose command names this hook's
script for that event."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
MARKER = "cat-mode-default/claude_prompt_submit.py"
FRAGMENT_PATH = os.path.join(HERE, "claude.prompt.hook.json")
HOOK_TYPE = "UserPromptSubmit"
AGENT_MARKER = "cat-mode-default/claude_pretooluse_agent.py"
AGENT_FRAGMENT_PATH = os.path.join(HERE, "claude.agent.hook.json")
AGENT_HOOK_TYPE = "PreToolUse"

HOOK_SPECS = [
    (HOOK_TYPE, MARKER, FRAGMENT_PATH),
    (AGENT_HOOK_TYPE, AGENT_MARKER, AGENT_FRAGMENT_PATH),
]


def _is_ours(entry: dict, marker: str = MARKER) -> bool:
    return any(marker in h.get("command", "") for h in entry.get("hooks", []))


def merge_hook(settings: dict, fragment: dict, hook_type: str = HOOK_TYPE, marker: str = MARKER) -> tuple[dict, bool]:
    settings = json.loads(json.dumps(settings))
    entry_list = settings.setdefault("hooks", {}).setdefault(hook_type, [])
    new_entries = fragment["hooks"][hook_type]
    before = json.dumps(entry_list, sort_keys=True)
    entry_list[:] = [e for e in entry_list if not _is_ours(e, marker)] + new_entries
    return settings, json.dumps(entry_list, sort_keys=True) != before


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as handle:
            settings = json.load(handle)
    any_changed = False
    for hook_type, marker, fragment_path in HOOK_SPECS:
        with open(fragment_path) as handle:
            fragment = json.load(handle)
        settings, changed = merge_hook(settings, fragment, hook_type, marker)
        if changed:
            any_changed = True
            print(f"link    claude {hook_type} cat-mode-default merged into settings.json")
        else:
            print(f"ok      claude {hook_type} cat-mode-default already up to date")
    if not any_changed:
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
