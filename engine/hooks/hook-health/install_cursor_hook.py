from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")
HERE = os.path.dirname(os.path.abspath(__file__))
FRAGMENT_PATH = os.path.join(HERE, "cursor.hook.json")
MARKER = "hook-health/cursor_before_submit.py"
EVENT = "beforeSubmitPrompt"


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
    print("fix    cursor hooks.json was a symlink; replaced with a real merged file")
    return True


def merge(data: dict, fragment: dict) -> bool:
    hooks = data.setdefault("hooks", {})
    entries = list(hooks.get(EVENT, []))
    incoming = fragment.get("hooks", {}).get(EVENT, [])
    before = json.dumps(entries, sort_keys=True)
    hooks[EVENT] = [entry for entry in entries if MARKER not in str(entry.get("command", ""))] + incoming
    return json.dumps(hooks[EVENT], sort_keys=True) != before


def main() -> None:
    materialized = materialize_real_file_if_symlink()
    data = load_hooks()
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)
    changed = merge(data, fragment)
    if not changed and not materialized:
        print("ok      cursor beforeSubmitPrompt hook-health already up to date")
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("link    cursor beforeSubmitPrompt hook-health merged")


if __name__ == "__main__":
    main()
