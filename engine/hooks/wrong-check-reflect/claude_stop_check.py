#!/usr/bin/env python3
"""Claude Code Stop hook: inject reflect on first-person wrong-check admission.

Exit 2 with the reflect prompt when the last assistant message admits a prior
check/claim was wrong. Fail-open.
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
    except Exception:
        return
    if message:
        sys.stderr.write(message + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
