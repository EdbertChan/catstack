#!/usr/bin/env python3
"""Claude Code Stop hook: record well-formed CAT-UNVERIFIED tags against the
session. Never blocks -- the tag exists for checks that cannot run now, so
blocking here would deadlock the turn. Fails open on read or parse errors.
"""
from __future__ import annotations

import json
import sys

from detect import decide_stop


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"unverified-tag-ledger: unreadable payload, allowing: {exc!r}\n")
        return
    try:
        note = decide_stop(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"unverified-tag-ledger: detector error, allowing this reply: {exc!r}\n")
        return
    if note:
        sys.stderr.write(note + "\n")


if __name__ == "__main__":
    main()
