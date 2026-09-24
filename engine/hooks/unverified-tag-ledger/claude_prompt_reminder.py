#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: surface CAT-UNVERIFIED claims that
earlier turns deferred and never settled. This is where cat-mode/SKILL.md:269
gets teeth -- the Stop hook cannot block the turn that emits a tag without
deadlocking, so the reminder lands on the next prompt instead.

How much it says is CATSTACK_UNVERIFIED_TAG_BEHAVIOR: off, stale (default),
all, or do_not_emit. Rows keep being recorded on every setting. do_not_emit
replaces the list with a standing instruction to leave unchecked claims out;
the Stop hook enforces it.
"""
from __future__ import annotations

import json
import sys

from detect import reminder, behavior_mode


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"unverified-tag-ledger: unreadable payload, no reminder: {exc!r}\n")
        return
    payload = payload if isinstance(payload, dict) else {}
    try:
        mode, note = behavior_mode(cwd=payload.get("cwd"))
        if note:
            sys.stderr.write(note + "\n")
        text = reminder(str(payload.get("session_id") or ""), mode)
    except Exception as exc:
        sys.stderr.write(f"unverified-tag-ledger: reminder error, continuing: {exc!r}\n")
        return
    if text:
        print(text)


if __name__ == "__main__":
    main()
