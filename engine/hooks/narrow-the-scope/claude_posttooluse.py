#!/usr/bin/env python3
"""Claude Code PostToolUse: inject the narrow-the-scope reminder once when a
file reaches three edits with no verification command between. Fail-open.
"""
from __future__ import annotations

import json
import sys

from detect import observe


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        text = observe(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if not text:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))


if __name__ == "__main__":
    main()
