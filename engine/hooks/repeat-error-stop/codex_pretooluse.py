#!/usr/bin/env python3
"""Codex PreToolUse: deny re-running a command that already hit the repeated error."""
from __future__ import annotations

import json
import sys

from detect import tool_block_reason


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = tool_block_reason(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        print(f"catstack-hook-error repeat-error-stop: {type(exc).__name__}: {exc}", file=sys.stderr)
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
