#!/usr/bin/env python3
"""Claude Code Stop hook for gate-blame-needs-evidence."""
from __future__ import annotations

import json
import sys

from detect import try_enqueue_judge


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    try_enqueue_judge(payload if isinstance(payload, dict) else {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
