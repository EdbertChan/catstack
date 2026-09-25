#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"followup_message": ""}))
        return
    try:
        from detect import try_check_reply

        try_check_reply(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        print(f"catstack-hook-error unverified-tag-check: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps({"followup_message": ""}))


if __name__ == "__main__":
    main()
