#!/usr/bin/env python3
"""Claude PostToolUseFailure + PostToolUse: count identical failure signatures; block on the third.

PostToolUse (success) only feeds successful edits, which restart the count;
a successful call's output is never scanned for error-looking text.
"""
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
    event_name = str(payload.get("hook_event_name") or "PostToolUse")
    if kind == "block":
        print(json.dumps({
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {"hookEventName": event_name, "additionalContext": reason},
        }))
    elif kind == "nudge":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": reason}}))


if __name__ == "__main__":
    main()
