#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): refuse a multi-line remote payload sent
through nested quoting, where the newlines do not survive. Exit 2 blocks; any
error fails open.
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
        sys.stderr.write(f"remote-payload-collapses: detector error, allowing this call: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
