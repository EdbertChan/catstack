#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]
    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"catstack-hook-error unverified-tag-check: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict) or payload.get("type") != "agent-turn-complete":
        return
    try:
        from detect import try_check_reply

        try_check_reply(payload)
    except Exception as exc:
        print(f"catstack-hook-error unverified-tag-check: {type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
