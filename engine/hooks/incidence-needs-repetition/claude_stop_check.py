#!/usr/bin/env python3
"""Claude Code Stop hook: a claim about behaviour across runs ("deterministic",
"flaky", "every run") in a turn that measured it once blocks with exit 2.
Fails open on read or parse errors; `stop_hook_active` skips so the rewrite
turn can finish.
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
        sys.stderr.write(f"incidence-needs-repetition: detector error, allowing this reply: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
