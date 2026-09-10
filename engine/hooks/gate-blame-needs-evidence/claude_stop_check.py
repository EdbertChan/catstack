#!/usr/bin/env python3
"""Claude Code Stop hook: a reply that blames a gate, tells the user to type
fewer items than its refusal requires, or asks to disable it, needs a
successful read of the gate's refusal-text file earlier in the session.
Blocks with exit 2; an unreadable transcript is reported as unchecked on
stderr and let through; `stop_hook_active` skips so the rewrite turn can
finish.
"""
from __future__ import annotations

import json
import sys

from detect import FEEDBACK, UNCHECKED, decide_stop


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        status, message = decide_stop(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"gate-blame-needs-evidence: detector error, allowing this reply: {exc!r}\n")
        return
    if status == UNCHECKED:
        sys.stderr.write(message + "\n")
        return
    if status != FEEDBACK:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
