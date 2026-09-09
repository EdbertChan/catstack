#!/usr/bin/env python3
"""Claude Stop hook: a turn that ran `gh pr merge` cannot end until it has
checked where the merge commit landed. Exits 2 with the verification command
on stderr. Fails open on a missing or unreadable transcript; `stop_hook_active`
skips so the follow-up turn can finish.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import decide_stop


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        message = decide_stop(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"gh-write-verification: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
