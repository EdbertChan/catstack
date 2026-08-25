#!/usr/bin/env python3
"""Cursor stop / sessionEnd for reflect-on-thrash.

`stop` (mid-turn) only records a deferred marker — empty followup_message so
the current task is not stolen. `sessionEnd` delivers the reflect prompt.
Fail-open. Pass `sessionEnd` as argv from the sessionEnd hook entry.
"""
from __future__ import annotations

import json
import sys

from detect import decide


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"followup_message": ""}))
        return
    try:
        message = decide(
            payload if isinstance(payload, dict) else {},
            argv=sys.argv[1:],
        )
    except Exception:
        print(json.dumps({"followup_message": ""}))
        return
    print(json.dumps({"followup_message": message or ""}))


if __name__ == "__main__":
    main()
