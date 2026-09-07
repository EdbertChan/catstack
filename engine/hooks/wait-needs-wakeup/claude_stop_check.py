#!/usr/bin/env python3
"""Claude Code Stop hook: a reply that says it is waiting / watching / will
report must name a clock-time ETA and have a scheduled wakeup in the turn.
Blocks with exit 2; fails open on any read or parse error;
`stop_hook_active` skips so the rewrite turn can finish.
"""
from __future__ import annotations

import json
import sys

from detect import decide_stop


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        message = decide_stop(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"wait-needs-wakeup: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
