#!/usr/bin/env python3
"""Cursor stop / sessionEnd: one followup to run reflect when thrash is flagged.

Fail-open. Empty followup_message is a no-op. Marker makes it once per transcript.
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
