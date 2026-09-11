#!/usr/bin/env python3
"""Claude Code Stop hook: inject reflect on first-person wrong-check admission.

Exit 2 with the reflect prompt when the last assistant message admits a prior
check/claim was wrong. Fail-open. When the regex stays silent, ask the
background llm-judge instead; its verdict arrives on the next prompt.
"""
from __future__ import annotations

import json
import sys

from detect import decide, try_enqueue_judge


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    payload = payload if isinstance(payload, dict) else {}
    try:
        message = decide(payload)
    except Exception:
        return
    try_enqueue_judge(payload, bool(message))
    if message:
        sys.stderr.write(message + "\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
