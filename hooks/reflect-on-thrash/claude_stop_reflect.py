#!/usr/bin/env python3
"""Claude Code Stop hook: defer reflect; do not block the current turn.

Exit 2 would force an extra reflect turn and steal in-progress work.
Thrash is recorded as deferred. Run /reflect later, or wait for a harness
session-end hook. Fail-open.
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
        decide(
            payload if isinstance(payload, dict) else {},
            deliver=False,
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
