#!/usr/bin/env python3
"""Idempotently merge scope-lock into Claude settings."""
from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKERS = {
    "UserPromptSubmit": "scope-lock/claude_prompt_scope.py",
    "PreToolUse": "scope-lock/claude_pretool_scope.py",
}


def _is_ours(entry: dict, marker: str) -> bool:
    return any(marker in str(hook.get("command", "")) for hook in entry.get("hooks", []))


def merge_hooks(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)["hooks"]
    hooks = result.setdefault("hooks", {})
    for hook_type, marker in MARKERS.items():
        kept = [entry for entry in hooks.get(hook_type, []) if not _is_ours(entry, marker)]
        hooks[hook_type] = kept + fragment[hook_type]
    return result


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    merged = merge_hooks(settings)
    if merged == settings:
        print("ok      claude scope-lock hooks already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print("link    claude UserPromptSubmit + PreToolUse scope-lock merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
