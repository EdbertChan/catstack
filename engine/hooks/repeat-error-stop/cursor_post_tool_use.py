#!/usr/bin/env python3
"""Cursor postToolUse: same counter; surfaces the stop instruction as additional_context."""
from __future__ import annotations

import json
import sys

from detect import record_result


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = record_result(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if blocked:
        print(json.dumps({"additional_context": reason}))


if __name__ == "__main__":
    main()
