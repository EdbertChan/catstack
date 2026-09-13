#!/usr/bin/env python3
"""Claude Stop hook: note a verifier that passed earlier and failed later.

Advisory — stderr plus exit 0 — because a gate can legitimately start failing
when the turn broke it on purpose. Fail-open on any read/parse error.
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
    except Exception as exc:
        print(f"catstack-hook-error verdict-flip-watch: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    if message:
        sys.stderr.write(message + "\n")


if __name__ == "__main__":
    main()
