#!/usr/bin/env python3
"""Claude Code Stop hook: block finishing on a thin-evidence remote-host
restart-safety claim.

Fail-open on any read/parse error. `stop_hook_active` skips so the
follow-up turn can finish once the missing check is run.
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
    except Exception:
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
