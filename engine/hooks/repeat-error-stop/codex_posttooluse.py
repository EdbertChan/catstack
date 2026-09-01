#!/usr/bin/env python3
"""Codex PostToolUse: same counter as Claude; emits the block decision as JSON."""
from __future__ import annotations

import json
import sys

from detect import record_result


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = record_result(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if blocked:
        print(json.dumps({
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reason},
        }))


if __name__ == "__main__":
    main()
