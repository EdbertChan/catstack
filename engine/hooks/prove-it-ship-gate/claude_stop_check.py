#!/usr/bin/env python3
"""Claude Code Stop hook: block a done/shipped/live claim about live-side-effect
work when the message carries no live evidence and no `UNVERIFIED: live path`.

Fail-open on any read/parse error. `stop_hook_active` skips so the follow-up
turn can finish once evidence is added.
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
