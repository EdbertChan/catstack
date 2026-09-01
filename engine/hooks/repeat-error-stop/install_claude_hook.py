#!/usr/bin/env python3
"""Idempotently merge repeat-error-stop into ~/.claude/settings.json."""
from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
FRAGMENT_PATH = os.path.join(HERE, "claude.hook.json")
MARKERS = {
    "UserPromptSubmit": "repeat-error-stop/claude_prompt_reset.py",
    "PreToolUse": "repeat-error-stop/claude_pretooluse.py",
    "PostToolUseFailure": "repeat-error-stop/claude_posttooluse.py",
    "PostToolUse": "repeat-error-stop/claude_posttooluse.py",
}


def _is_ours(entry: dict, marker: str) -> bool:
    return any(marker in str(h.get("command", "")) for h in entry.get("hooks", []))


def merge_hooks(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    hooks = result.setdefault("hooks", {})
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)["hooks"]
    for event, marker in MARKERS.items():
        kept = [e for e in hooks.get(event, []) if not _is_ours(e, marker)]
        hooks[event] = kept + fragment.get(event, [])
        if not hooks[event]:
            del hooks[event]
    return result


def main() -> None:
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    merged = merge_hooks(settings)
    if merged == settings:
        print("ok      claude repeat-error-stop hooks already up to date")
        return
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print("link    claude UserPromptSubmit + PreToolUse + PostToolUse + PostToolUseFailure repeat-error-stop merged")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
