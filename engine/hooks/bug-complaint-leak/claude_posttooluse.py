#!/usr/bin/env python3
"""PostToolUse: record empty Grep results; clear repeat-sig on edits; note git history lookups.

Claude Code and Cursor both can feed this script (tool names differ slightly).
Fail-open.
"""
from __future__ import annotations

import json
import re
import sys

from state import (
    clear_empty_greps,
    note_edit,
    note_git_history_lookup,
    record_empty_grep,
)


def _tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def _tool_result_text(payload: dict) -> str:
    for key in ("tool_result", "toolResult", "result", "output", "stdout"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for inner in ("content", "output", "stdout", "text"):
                if isinstance(value.get(inner), str):
                    return value[inner]
    return ""


GIT_HISTORY_RE = re.compile(
    r"git\s+(?:grep\s+origin/master|log\s+(?:--all\s+)?-S|log\s+--oneline\s+--all\s+--grep)",
    re.I,
)


def _looks_empty_grep(result: str) -> bool:
    text = (result or "").strip()
    if not text:
        return True
    lowered = text.lower()
    empty_markers = (
        "no matches",
        "no files with matches",
        "0 matches",
        "found 0",
        "(no results)",
    )
    return any(marker in lowered for marker in empty_markers)


def process(payload: dict) -> None:
    name = _tool_name(payload)
    tool_input = _tool_input(payload)

    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace", "Delete"):
        note_edit(payload)
        return

    if name in ("Bash", "Shell", "shell"):
        command = str(tool_input.get("command") or "")
        if GIT_HISTORY_RE.search(command):
            note_git_history_lookup(payload)
        return

    if name not in ("Grep", "grep", "rg"):
        return

    pattern = str(tool_input.get("pattern") or tool_input.get("query") or "")
    path = tool_input.get("path")
    glob = tool_input.get("glob")
    if isinstance(path, list):
        path = path[0] if path else ""
    result = _tool_result_text(payload)
    if _looks_empty_grep(result):
        record_empty_grep(payload, pattern, str(path or ""), str(glob or ""))
    else:
        clear_empty_greps(payload)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        process(payload)
    except Exception:
        return


if __name__ == "__main__":
    main()
