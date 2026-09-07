#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Edit|Write|MultiEdit|Bash): advisory scan of
new code for silent-failure shapes. Never blocks: exit 0, the findings go to
the agent as additionalContext and to stderr. Fail-open on any error.
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
        message = decide(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"explicit-failures: scanner error, skipping this edit: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message},
    }))


if __name__ == "__main__":
    main()
