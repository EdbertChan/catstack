#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: refuse a direct write to Invoker's live SQLite
database and name the headless command that owns the same state. Exits 2
with the message on stderr.

Positive-lists shell-like tool names, so a Write/Edit whose *content*
mentions these shapes is never blocked. Fails open on any parse error or
unexpected detector exception; an entry point the detector cannot classify
is reported as unchecked and blocked, which is the one deliberate
fail-closed path.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import pretooluse_outcome


def main() -> None:
    raw = sys.stdin.read()
    try:
        outcome, messages = pretooluse_outcome(raw)
    except Exception as exc:
        sys.stderr.write(f"invoker-db-guard: detector error, allowing this command: {exc!r}\n")
        return
    if outcome == "clean" or not messages:
        return
    sys.stderr.write("\n\n".join(messages) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
