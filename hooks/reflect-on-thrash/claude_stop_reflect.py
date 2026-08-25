#!/usr/bin/env python3
"""Claude Code Stop hook: defer ordinary thrash; inject on intervention.

Exit 2 with the reflect+automate-me prompt only when
`intervention-must-automate` fired — same-type complaints must not wait
for session end. Ordinary thrash still records a deferred marker (exit 0)
so in-progress work is not stolen. Fail-open.
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
        message = decide(
            payload if isinstance(payload, dict) else {},
        )
    except Exception:
        return
    if message:
        sys.stderr.write(message + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
