#!/usr/bin/env python3
"""Cursor stop / sessionEnd hook for wrong-check-reflect."""
from __future__ import annotations

import json
import sys

from detect import try_enqueue_judge


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"followup_message": ""}))
        return
    payload = payload if isinstance(payload, dict) else {}
    try_enqueue_judge(payload)
    print(json.dumps({"followup_message": ""}))


if __name__ == "__main__":
    main()
