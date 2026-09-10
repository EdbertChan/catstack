#!/usr/bin/env python3
"""Claude Code Stop hook: a reply that blames a hook, gate, lock or checker
must rest on a read of that gate's source in the session, or cite its rule
as file:line. Sends the reply back with exit 2 (it never blocks a tool
call); `stop_hook_active` skips so the rewrite turn can finish. An
unreadable transcript is reported on stderr as unchecked and fails open.
"""
from __future__ import annotations

import json
import sys

from detect import HIT, UNCHECKED, check_stop


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        outcome, message = check_stop(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"gate-blame-needs-evidence: detector error, allowing this reply: {exc!r}\n")
        return
    if outcome == UNCHECKED:
        sys.stderr.write(f"{message}\n")
        return
    if outcome != HIT:
        return
    sys.stderr.write(f"{message}\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
