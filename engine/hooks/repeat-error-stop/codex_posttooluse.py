#!/usr/bin/env python3
"""Codex PostToolUse: same counter as Claude; emits the block decision as JSON."""
from __future__ import annotations

import json
import sys

from detect import record_result


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        kind, reason = record_result(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        print(f"catstack-hook-error repeat-error-stop: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    if kind == "block":
        print(json.dumps({
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reason},
        }))
    elif kind == "nudge":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reason}}))


if __name__ == "__main__":
    main()
