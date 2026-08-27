#!/usr/bin/env python3
"""Claude PreToolUse hook: enforce the current session's scope lock."""
from __future__ import annotations

import json
import sys

from detect import tool_block_reason


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        blocked, reason = tool_block_reason(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if blocked:
        sys.stderr.write(reason + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
