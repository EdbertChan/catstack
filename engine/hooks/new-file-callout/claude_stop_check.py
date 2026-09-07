#!/usr/bin/env python3
"""Claude Code Stop hook: untracked files this turn left at the repo root or
under scripts/ must be named in the reply. Blocks with exit 2; fails open
on read, parse, or git errors; `stop_hook_active` skips.
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
        sys.stderr.write(f"new-file-callout: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
