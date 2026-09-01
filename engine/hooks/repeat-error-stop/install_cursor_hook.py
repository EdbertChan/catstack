#!/usr/bin/env python3
"""Idempotently merge repeat-error-stop into Cursor hooks.json."""
from __future__ import annotations

import copy
import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")
FRAGMENT = {
    "beforeSubmitPrompt": [{
        "command": "python3 $HOME/.cursor/hooks/repeat-error-stop/cursor_before_submit.py",
        "timeout": 5,
    }],
    "preToolUse": [{
        "matcher": "*",
        "command": "python3 $HOME/.cursor/hooks/repeat-error-stop/cursor_pretool.py",
        "timeout": 5,
    }],
    "postToolUse": [{
        "matcher": "*",
        "command": "python3 $HOME/.cursor/hooks/repeat-error-stop/cursor_post_tool_use.py",
        "timeout": 5,
    }],
}
MARKERS = {key: entries[0]["command"].split("$HOME/.cursor/hooks/")[1] for key, entries in FRAGMENT.items()}


def merge_hooks(data: dict) -> dict:
    result = copy.deepcopy(data)
    result.setdefault("version", 1)
    hooks = result.setdefault("hooks", {})
    for hook_type, incoming in FRAGMENT.items():
        marker = MARKERS[hook_type]
        kept = [entry for entry in hooks.get(hook_type, []) if marker not in str(entry.get("command", ""))]
        hooks[hook_type] = kept + copy.deepcopy(incoming)
    return result


def main() -> None:
    if os.path.islink(HOOKS_PATH):
        print("skip    cursor hooks.json is a symlink; run the bug-complaint-leak installer first")
        return
    data: dict = {"version": 1, "hooks": {}}
    if os.path.exists(HOOKS_PATH):
        with open(HOOKS_PATH, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    merged = merge_hooks(data)
    if merged == data:
        print("ok      cursor repeat-error-stop hooks already up to date")
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print("link    cursor beforeSubmitPrompt + preToolUse + postToolUse repeat-error-stop merged")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
