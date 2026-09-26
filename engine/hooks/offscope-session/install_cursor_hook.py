#!/usr/bin/env python3
"""Idempotently merge offscope-session into ~/.cursor/hooks.json.

~/.cursor/hooks.json used to be a symlink to one hook's fragment, which no
longer works once several hooks share the file, so a symlink found here is
turned into a real merged file first. After that only the entry naming this
hook's own entrypoint is replaced, so a second `./install.sh` run changes
nothing.
"""
from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")
FRAGMENT_PATH = os.path.join(HERE, "cursor.hook.json")
EVENT = "beforeSubmitPrompt"
MARKER = "offscope-session/cursor_before_submit.py"


def load_hooks() -> dict:
    if not os.path.exists(HOOKS_PATH):
        return {"version": 1, "hooks": {}}
    with open(HOOKS_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"version": 1, "hooks": {}}
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    return data


def materialize_real_file_if_symlink() -> bool:
    if not os.path.islink(HOOKS_PATH):
        return False
    data = load_hooks()
    os.unlink(HOOKS_PATH)
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("fix     cursor hooks.json was a symlink; replaced with a real merged file")
    return True


def merge(data: dict, fragment: dict) -> bool:
    hooks = data.setdefault("hooks", {})
    entries = list(hooks.get(EVENT, []))
    before = json.dumps(entries, sort_keys=True)
    incoming = copy.deepcopy(fragment.get("hooks", {}).get(EVENT, []))
    hooks[EVENT] = [e for e in entries if MARKER not in str(e.get("command", ""))] + incoming
    return json.dumps(hooks[EVENT], sort_keys=True) != before


def main() -> None:
    materialized = materialize_real_file_if_symlink()
    data = load_hooks()
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)
    changed = merge(data, fragment)
    if not changed and not materialized:
        print("ok      cursor offscope-session hooks already up to date")
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("link    cursor beforeSubmitPrompt offscope-session merged")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
