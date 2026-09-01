#!/usr/bin/env python3
"""Merge build-the-lever Cursor hooks into ~/.cursor/hooks.json without wiping others."""
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")

FRAGMENT = {
    "beforeSubmitPrompt": [
        {
            "command": "python3 $HOME/.cursor/hooks/build-the-lever/cursor_before_submit.py",
            "timeout": 10,
        }
    ],
    "postToolUse": [
        {
            "command": "python3 $HOME/.cursor/hooks/build-the-lever/cursor_post_tool_use.py",
            "timeout": 5,
        }
    ],
}

MARKERS = {
    "beforeSubmitPrompt": "build-the-lever/cursor_before_submit.py",
    "postToolUse": "build-the-lever/cursor_post_tool_use.py",
}

DIU_STOP = {
    "type": "prompt",
    "prompt": (
        "Find the assistant's last response in this conversation and check it against this rule: "
        "it should read under ~150 words and be free of unexplained jargon, UNLESS the user's last "
        "message explicitly asked for full technical detail, a specific long format (a PR summary, "
        "a written plan, a file list), or the response already applies an explicit ELI5 word cap "
        "the user gave. Output ONLY a single JSON object and nothing else -- no explanation, no "
        "analysis, no markdown fences, before or after it. If it violates the rule and none of "
        "those exceptions apply, output exactly: {\"followup_message\": \"Apply diu: rewrite under "
        "40 words, plain language.\"}. Otherwise output exactly: {\"followup_message\": \"\"}."
    ),
    "timeout": 30,
}


def _is_ours(entry: dict, marker: str) -> bool:
    return marker in str(entry.get("command", ""))


def merge_list(existing: list, incoming: list, marker: str) -> list:
    kept = [e for e in existing if not _is_ours(e, marker)]
    return kept + incoming


def load_hooks() -> dict:
    if not os.path.exists(HOOKS_PATH) and not os.path.islink(HOOKS_PATH):
        return {"version": 1, "hooks": {"stop": [DIU_STOP]}}
    with open(HOOKS_PATH) as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"version": 1, "hooks": {"stop": [DIU_STOP]}}
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    data["hooks"].setdefault("stop", [DIU_STOP])
    return data


def materialize_real_file_if_symlink() -> bool:
    if not os.path.islink(HOOKS_PATH):
        return False
    data = load_hooks()
    os.unlink(HOOKS_PATH)
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("fix    cursor hooks.json was a symlink; replaced with a real merged file")
    return True


def main() -> None:
    materialize_real_file_if_symlink()
    data = load_hooks()
    hooks = data.setdefault("hooks", {})

    changed = False
    for key, incoming in FRAGMENT.items():
        before = json.dumps(hooks.get(key, []), sort_keys=True)
        hooks[key] = merge_list(list(hooks.get(key, [])), incoming, MARKERS[key])
        after = json.dumps(hooks[key], sort_keys=True)
        if before != after:
            changed = True
            print(f"link    cursor {key} build-the-lever merged")
        else:
            print(f"ok      cursor {key} build-the-lever already up to date")

    stop = list(hooks.get("stop") or [])
    if not any("Apply diu" in str(e.get("prompt", "")) for e in stop):
        hooks["stop"] = [DIU_STOP] + stop
        changed = True
        print("link    cursor stop diu entry restored")

    if not changed and not os.path.islink(HOOKS_PATH):
        return

    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
