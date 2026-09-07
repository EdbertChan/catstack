#!/usr/bin/env python3
"""Claude Code PreToolUse (Agent): carry the cat-mode default into subagents.

A subagent's prompt arrives through the Agent tool, so the UserPromptSubmit
hook next to this file never sees it. When CATSTACK_CAT_MODE_DEFAULT
resolves to on and the prompt does not already mention cat-mode, this
returns `hookSpecificOutput.updatedInput` with the same tool_input and the
prompt prefixed by one line naming the installed SKILL.md.

Fail-open. No LLM. Never denies or asks; it only rewrites the prompt.
"""
from __future__ import annotations

import json
import sys

from detect import agent_updated_input


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        updated = agent_updated_input(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if updated is None:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated,
        }
    }))


if __name__ == "__main__":
    main()
