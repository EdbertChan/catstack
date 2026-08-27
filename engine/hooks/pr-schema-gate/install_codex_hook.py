#!/usr/bin/env python3
"""Merge pr-schema-gate's Codex pre_tool_use hook into ~/.codex/hooks.json.

UNVERIFIED SCHEMA: Codex CLI (0.146.0) advertises `hooks: stable` in
`codex features list` and tracks trusted-hash state for
`hooks.json:pre_tool_use:<idx>:<idx>` entries in config.toml, but the
project ships no local docs/schema for hooks.json's shape. The nested
`event:idx:idx` key format matches Claude's own
`{"pre_tool_use": [{"matcher": ..., "hooks": [{"type": "command", ...}]}]}`
shape closely enough that this installer assumes parity with it -- reuses
claude_pretooluse.py unmodified, same as the Cursor installer.

This has NOT been confirmed against a live Codex hook firing. After
install, smoke-test it (see README.md) before trusting it to block
anything -- Codex's own approval/trust mechanism additionally requires the
hooks.json content to match a previously-trusted sha256 in config.toml's
[hooks.state] table, or the hook may be silently ignored until approved
inside Codex.
"""
from __future__ import annotations

import json
import os

HOOKS_PATH = os.path.expanduser("~/.codex/hooks.json")
MARKER = "pr-schema-gate/claude_pretooluse.py"

FRAGMENT_ENTRY = {
    "matcher": "exec",
    "hooks": [
        {
            "type": "command",
            "command": "python3 $HOME/.codex/hooks/pr-schema-gate/claude_pretooluse.py",
            "timeout": 5,
        }
    ],
}


def _is_ours(entry: dict) -> bool:
    for h in entry.get("hooks", []):
        if MARKER in str(h.get("command", "")):
            return True
    return False


def load_hooks() -> dict:
    if not os.path.exists(HOOKS_PATH):
        return {}
    with open(HOOKS_PATH) as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def main() -> None:
    data = load_hooks()

    existing = list(data.get("pre_tool_use", []))
    kept = [e for e in existing if not _is_ours(e)]
    new_list = kept + [FRAGMENT_ENTRY]

    if json.dumps(new_list, sort_keys=True) == json.dumps(existing, sort_keys=True):
        print("ok      codex pre_tool_use pr-schema-gate already up to date")
        return

    data["pre_tool_use"] = new_list
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("link    codex pre_tool_use pr-schema-gate merged (schema UNVERIFIED -- smoke-test it)")
    print("        Codex may also require re-trusting hooks.json's new hash on next launch.")


if __name__ == "__main__":
    main()
