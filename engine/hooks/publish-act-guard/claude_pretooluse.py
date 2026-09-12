#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: refuse a publishing command issued from inside a
subagent while a live Invoker owner is reachable.

Exits 2 with the refusal on stderr, which is how Claude Code turns a
PreToolUse hook into a block. Fails open on a payload that will not parse and
on any unexpected detector error; the liveness read has its own UNCHECKED
branch that allows the command and names the reason.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import decide


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        sys.stderr.write(f"publish-act-guard: payload did not parse ({exc}); allowing\n")
        return
    try:
        refusal = decide(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"publish-act-guard: check did not run ({exc}); allowing\n")
        return
    if refusal is None:
        return
    sys.stderr.write(refusal + "\n")
    if refusal.startswith("publish-act-guard: UNCHECKED"):
        return
    sys.exit(2)


if __name__ == "__main__":
    main()
