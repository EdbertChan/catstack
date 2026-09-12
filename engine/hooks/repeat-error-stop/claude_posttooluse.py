#!/usr/bin/env python3
"""Claude PostToolUseFailure + PostToolUse: count identical failure signatures; block on the third.

PostToolUse (success) feeds two things: error lines observed in exit-0 output
(log tails, test summaries) and successful edits, which restart the count.
"""
from __future__ import annotations

import json
import sys

from detect import record_result


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        kind, reason = record_result(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if kind == "block":
        print(json.dumps({
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {"hookEventName": str(payload.get("hook_event_name") or "PostToolUse"), "additionalContext": reason},
        }))
    elif kind == "nudge":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reason}}))


if __name__ == "__main__":
    main()
