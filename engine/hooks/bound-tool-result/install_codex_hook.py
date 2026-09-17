#!/usr/bin/env python3
"""Idempotently merge bound-tool-result into Codex's native hooks (~/.codex/hooks.json)."""
from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_PATH = os.path.expanduser("~/.codex/hooks.json")
FRAGMENT_PATH = os.path.join(HERE, "codex.hook.json")
MARKERS = {"PreToolUse": "bound-tool-result/codex_pre_tool_use.py"}


def _is_ours(entry: dict, marker: str) -> bool:
    return any(marker in str(h.get("command", "")) for h in entry.get("hooks", []))


def merge_hooks(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        result["hooks"] = hooks
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        fragment = json.load(handle)["hooks"]
    for event, marker in MARKERS.items():
        kept = [e for e in hooks.get(event, []) if not _is_ours(e, marker)]
        hooks[event] = kept + fragment[event]
    return result


def main() -> None:
    settings: dict = {}
    if os.path.exists(HOOKS_PATH):
        with open(HOOKS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    merged = merge_hooks(settings)
    if merged == settings:
        print("ok      codex PreToolUse bound-tool-result already up to date")
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print("link    codex PreToolUse bound-tool-result merged")
    print("        (review with /hooks, trust the definitions, then restart Codex)")


if __name__ == "__main__":
    main()
