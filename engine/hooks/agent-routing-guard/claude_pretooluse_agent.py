#!/usr/bin/env python3
"""Claude Code PreToolUse (Agent): refuse a subagent spawn that carries
publication work while invoker-cli is on PATH.

Exits 2 with the refusal on stderr, which is how Claude Code turns a
PreToolUse hook into a block. Fail-open on a payload that will not parse and
on any unexpected error in the detector; the one deliberate fail-closed path
is the local-override check, which lives in detect.py and blocks with its own
message when the user's current message could not be read.
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
    except (json.JSONDecodeError, OSError, ValueError):
        return
    try:
        refusal = decide(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"agent-routing-guard: check did not run ({exc}); allowing the spawn\n")
        return
    if refusal is None:
        return
    sys.stderr.write(refusal + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
