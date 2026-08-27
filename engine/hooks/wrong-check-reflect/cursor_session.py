#!/usr/bin/env python3
"""Cursor stop / sessionEnd for wrong-check-reflect.

`stop` delivers followup_message when the last assistant message admits a
prior check was wrong. `sessionEnd` stays silent if already prompted.
Fail-open.
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
        message = decide(payload if isinstance(payload, dict) else {})
    except Exception:
        print(json.dumps({"followup_message": ""}))
        return
    print(json.dumps({"followup_message": message or ""}))


if __name__ == "__main__":
    main()
