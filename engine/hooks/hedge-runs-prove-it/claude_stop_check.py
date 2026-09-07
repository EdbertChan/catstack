#!/usr/bin/env python3
"""Claude Code Stop hook: a hedge about code or repo state ("I think",
"probably", "should work", `UNVERIFIED:` with no reason) in a turn that ran
no verification tool blocks with exit 2. Fails open on read or parse
errors; `stop_hook_active` skips so the rewrite turn can finish.
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
        sys.stderr.write(f"hedge-runs-prove-it: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
