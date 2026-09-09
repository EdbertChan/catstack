#!/usr/bin/env python3
"""Claude Code PostToolUse: inject the answer-overrides-menu reminder when an
AskUserQuestion answer matches none of that question's offered labels.
A subagent's AskUserQuestion is not the human's, so agent turns are skipped.
Fail-open.
"""
from __future__ import annotations

import json
import sys

from detect import decide


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return
    try:
        text = decide(payload)
    except Exception:
        return
    if not text:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))


if __name__ == "__main__":
    main()
