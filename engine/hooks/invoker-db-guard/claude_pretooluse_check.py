#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): block a direct write to Invoker's live
SQLite database and name the invoker-cli command that does the same job.
Exit 2 blocks. A payload that cannot be read, or a detector error, allows the
call and says on stderr that it was not checked.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import decide  # noqa: E402


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"invoker-db-guard: hook payload unreadable, this call was not checked: {exc!r}\n")
        return
    if not isinstance(payload, dict):
        sys.stderr.write("invoker-db-guard: hook payload is not an object, this call was not checked\n")
        return
    try:
        message = decide(payload)
    except Exception as exc:
        sys.stderr.write(f"invoker-db-guard: detector error, this call was not checked and is allowed: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
