#!/usr/bin/env python3
"""Merge bug-complaint-leak Cursor hooks into ~/.cursor/hooks.json without wiping diu stop.

If hooks.json is currently a symlink into diu-stop (legacy install.sh layout),
replace it with a real file so merges never rewrite the diu-stop fragment.
"""
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.cursor/hooks.json")

FRAGMENT = {
    "beforeSubmitPrompt": [
        {
            "command": "python3 $HOME/.cursor/hooks/bug-complaint-leak/cursor_before_submit.py",
            "timeout": 10,
        }
    ],
    "preToolUse": [
        {
            "matcher": "Grep",
            "command": "python3 $HOME/.cursor/hooks/bug-complaint-leak/claude_pretooluse_grep.py",
            "timeout": 5,
        }
    ],
    "postToolUse": [
        {
            "command": "python3 $HOME/.cursor/hooks/bug-complaint-leak/cursor_post_tool_use.py",
            "timeout": 5,
        }
    ],
}

MARKERS = {
    "beforeSubmitPrompt": "bug-complaint-leak/cursor_before_submit.py",
    "preToolUse": "bug-complaint-leak/claude_pretooluse_grep.py",
    "postToolUse": "bug-complaint-leak/cursor_post_tool_use.py",
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
    with open(HOOKS_PATH) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": 1, "hooks": {"stop": [DIU_STOP]}}
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    data["hooks"].setdefault("stop", [DIU_STOP])
    return data


def materialize_real_file_if_symlink() -> bool:
    """Return True if we replaced a symlink with a real file."""
    if not os.path.islink(HOOKS_PATH):
        return False
    data = load_hooks()
    os.unlink(HOOKS_PATH)
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("fix    cursor hooks.json was a symlink into diu-stop; replaced with a real merged file")
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
            print(f"link    cursor {key} bug-complaint-leak merged")
        else:
            print(f"ok      cursor {key} bug-complaint-leak already up to date")

    # Ensure diu stop entry still present after materialize/merge.
    stop = list(hooks.get("stop") or [])
    if not any("Apply diu" in str(e.get("prompt", "")) for e in stop):
        hooks["stop"] = [DIU_STOP] + stop
        changed = True
        print("link    cursor stop diu entry restored")

    if not changed and not os.path.islink(HOOKS_PATH):
        # Still rewrite if we just materialised; materialize already wrote.
        return

    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("        (restart Cursor to pick up the change)")


if __name__ == "__main__":
    main()
