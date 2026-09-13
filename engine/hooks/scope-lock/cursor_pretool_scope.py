#!/usr/bin/env python3
"""Cursor preToolUse hook: enforce the current session's scope lock."""
from __future__ import annotations

import json
import sys

from detect import tool_block_reason


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = tool_block_reason(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        print(f"catstack-hook-error scope-lock: {type(exc).__name__}: {exc}", file=sys.stderr)
        blocked, reason = False, ""
    if blocked:
        print(json.dumps({"continue": False, "user_message": reason}))
    else:
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
