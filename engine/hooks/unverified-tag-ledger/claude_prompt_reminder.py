#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: surface CAT-UNVERIFIED claims that
earlier turns deferred and never settled. This is where cat-mode/SKILL.md:269
gets teeth -- the Stop hook cannot block the turn that emits a tag without
deadlocking, so the reminder lands on the next prompt instead.
"""
from __future__ import annotations

import json
import sys

from detect import reminder


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"unverified-tag-ledger: unreadable payload, no reminder: {exc!r}\n")
        return
    try:
        text = reminder(str((payload or {}).get("session_id") or ""))
    except Exception as exc:
        sys.stderr.write(f"unverified-tag-ledger: reminder error, continuing: {exc!r}\n")
        return
    if text:
        print(text)


if __name__ == "__main__":
    main()
