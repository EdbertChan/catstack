#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): block foreground poll loops and long
bare sleeps. The wait belongs to the harness (ScheduleWakeup / Monitor /
run_in_background that exits on the condition). Blocks with exit 2; fails
open on any read or parse error.
"""
from __future__ import annotations

import json
import sys

from detect import decide_pretooluse


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        message = decide_pretooluse(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"wait-needs-wakeup: detector error, allowing this command: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
