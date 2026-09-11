#!/usr/bin/env python3
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")
MARKER = "llm-judge/cursor_session.py"
COMMAND = "python3 $HOME/.cursor/hooks/llm-judge/cursor_session.py"

STOP_ENTRY = {
    "command": COMMAND,
    "timeout": 10,
    "loop_limit": 1,
}


def _is_ours(entry: dict) -> bool:
    return MARKER in str(entry.get("command", ""))


def merge_list(existing: list, incoming: dict) -> list:
    kept = [e for e in existing if not _is_ours(e)]
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
    before = json.dumps(hooks.get("stop", []), sort_keys=True)
    hooks["stop"] = merge_list(list(hooks.get("stop", [])), STOP_ENTRY)
    if json.dumps(hooks["stop"], sort_keys=True) == before:
        print("ok      cursor stop llm-judge already up to date")
        return
    print("link    cursor stop llm-judge merged")
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
