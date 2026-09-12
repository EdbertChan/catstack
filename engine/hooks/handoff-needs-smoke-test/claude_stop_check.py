#!/usr/bin/env python3
"""Claude Code Stop hook: block a reply that hands the user a script this
session never ran, unless the reply names why the run cannot happen here.
Fails open on read or parse errors; `stop_hook_active` skips.
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
        sys.stderr.write(f"handoff-needs-smoke-test: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
