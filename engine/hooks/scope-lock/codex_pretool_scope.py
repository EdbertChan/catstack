#!/usr/bin/env python3
"""Codex PreToolUse hook: deny tools while the session scope lock is active."""
from __future__ import annotations

import json
import sys

from detect import tool_block_reason


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = tool_block_reason(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if blocked:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))


if __name__ == "__main__":
    main()
