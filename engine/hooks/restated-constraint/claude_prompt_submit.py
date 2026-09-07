#!/usr/bin/env python3
"""Claude Code UserPromptSubmit: flag a constraint the user already named.

Advisory only. Fail-open. No LLM. Never denies the prompt.
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
    try:
        context = decide(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if not context:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
