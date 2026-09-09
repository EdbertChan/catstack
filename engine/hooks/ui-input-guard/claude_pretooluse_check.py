#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): block synthetic keyboard, mouse, and
screen-capture commands aimed at the user's live session unless a hands-off
window is open, the screen is unlocked, and the user is idle. Exit 2 blocks;
any error fails open.
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
        sys.stderr.write(f"ui-input-guard: detector error, allowing this call: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
