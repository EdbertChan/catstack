#!/usr/bin/env python3
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")

FRAGMENT = {
    "stop": {
        "command": "python3 $HOME/.cursor/hooks/llm-judge/cursor_session.py",
        "timeout": 10,
        "loop_limit": 1,
    },
    "postToolUse": {
        "command": "python3 $HOME/.cursor/hooks/llm-judge/cursor_post_tool_use.py",
        "timeout": 5,
    },
}

MARKERS = {
    "stop": "llm-judge/cursor_session.py",
    "postToolUse": "llm-judge/cursor_post_tool_use.py",
}


def _is_ours(entry: dict, marker: str) -> bool:
    return marker in str(entry.get("command", ""))


def merge_list(existing: list, incoming: dict, marker: str) -> list:
    kept = [e for e in existing if not _is_ours(e, marker)]
    return kept + [incoming]


def main() -> None:
    if os.path.islink(HOOKS_PATH):
        print(
            "skip    cursor hooks.json is a symlink; bug-complaint-leak installer materializes it first"
        )
        return
    data: dict = {"version": 1, "hooks": {}}
    if os.path.exists(HOOKS_PATH):
        with open(HOOKS_PATH) as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})

    changed = False
    for key, incoming in FRAGMENT.items():
        before = json.dumps(hooks.get(key, []), sort_keys=True)
        hooks[key] = merge_list(list(hooks.get(key, [])), incoming, MARKERS[key])
        if json.dumps(hooks[key], sort_keys=True) == before:
            print(f"ok      cursor {key} llm-judge already up to date")
        else:
            changed = True
            print(f"link    cursor {key} llm-judge merged")

    if not changed:
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
