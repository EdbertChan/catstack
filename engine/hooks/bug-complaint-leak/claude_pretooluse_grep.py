#!/usr/bin/env python3
"""Claude/Cursor PreToolUse Grep: after two empty greps of user-quoted copy, require origin/master.

Also blocks exact-repeat Grep (path, pattern, glob) with no intervening edit.
Fail-open on parse errors.
"""
from __future__ import annotations

import json
import sys

from state import (
    consecutive_empty_for_quote,
    grep_signature,
    load_state,
)


def _tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        name = _tool_name(payload)
        if name not in ("Grep", "grep", "rg"):
            return
        tool_input = _tool_input(payload)
        pattern = str(tool_input.get("pattern") or tool_input.get("query") or "")
        path = tool_input.get("path")
        glob = tool_input.get("glob")
        if isinstance(path, list):
            path = path[0] if path else ""
        path_s = str(path or "")
        glob_s = str(glob or "")

        state = load_state(payload)
        bug = state.get("bug_complaint") or {}
        quotes = list(bug.get("quotes") or [])

        # Only enforce exact-repeat when we actually saw a pattern. Empty
        # signatures mean the host used a different tool_input shape — fail open.
        sig = grep_signature(pattern, path_s, glob_s) if pattern.strip() else None
        if sig and state.get("last_grep_sig") == sig:
            sys.stderr.write(
                "Exact-repeat Grep with no intervening edit. Change path/pattern/glob, "
                "or Read the file after an edit — repeating the same empty Grep is not progress.\n"
            )
            sys.exit(2)

        if quotes and consecutive_empty_for_quote(state, quotes) >= 2 and not state.get("did_origin_lookup"):
            sample = quotes[0]
            sys.stderr.write(
                "Workspace Grep of user-quoted product copy returned empty twice. "
                f"Before more local Grep, run: git grep origin/master -e {sample!r} "
                f"and/or git log --all -S {sample!r}. Fail-open checklist lives in bug-complaint-leak.\n"
            )
            sys.exit(2)

        # Persist signature for next Grep; post-edit hook clears it.
        if sig:
            state["last_grep_sig"] = sig
            from state import save_state

            save_state(payload, state)
    except Exception:
        return


if __name__ == "__main__":
    main()
