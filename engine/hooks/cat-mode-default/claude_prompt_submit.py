#!/usr/bin/env python3
"""Claude Code UserPromptSubmit: inject the cat-mode default context.

Fail-open. No LLM. Never denies. Silent unless CATSTACK_CAT_MODE_DEFAULT
resolves to on and the prompt does not contain a typed /cat-mode.
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
    except Exception as exc:
        print(f"catstack-hook-error cat-mode-default: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    if context is None:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
