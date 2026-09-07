#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Write|Edit|MultiEdit|NotebookEdit|Bash):
block a write into a shared scratchpad file another agent touched within
the last ten minutes. Blocks with exit 2; fails open on any error.
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
        sys.stderr.write(f"scratchpad-collision: detector error, allowing this write: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
