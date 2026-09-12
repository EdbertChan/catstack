#!/usr/bin/env python3
"""Cursor postToolUse: inject pending bug-complaint checklist once via additional_context."""
from __future__ import annotations

import json
import sys

from claude_posttooluse import process as record_tool_outcome
from state import load_state, save_state


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        record_tool_outcome(payload)
        state = load_state(payload)
        if not state.get("cursor_checklist_pending"):
            return
        bug = state.get("bug_complaint") or {}
        checklist = bug.get("checklist")
        if not checklist:
            return
        state["cursor_checklist_pending"] = False
        save_state(payload, state)
        print(json.dumps({"additional_context": checklist}))
    except Exception:
        return


if __name__ == "__main__":
    main()
