#!/usr/bin/env python3
"""Claude Code Stop hook for named-verb-guard."""
from __future__ import annotations

import json
import sys

from detect import try_enqueue_judge


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try_enqueue_judge(payload if isinstance(payload, dict) else {})


if __name__ == "__main__":
    main()
