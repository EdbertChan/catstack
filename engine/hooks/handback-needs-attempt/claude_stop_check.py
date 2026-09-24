#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from detect import try_enqueue_judge


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"catstack-hook-unchecked handback-needs-attempt: unreadable payload: {exc}", file=sys.stderr)
        return
    try_enqueue_judge(payload if isinstance(payload, dict) else {})


if __name__ == "__main__":
    main()
