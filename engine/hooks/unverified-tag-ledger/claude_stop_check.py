#!/usr/bin/env python3
"""Claude Code Stop hook: record well-formed CAT-UNVERIFIED tags against the
session, and refuse a turn that tags a claim without having run any
verification tool (cat-mode/SKILL.md:269 -- a hedge is a trigger to verify).
`stop_hook_active` releases the refusal so the rewrite turn can finish. Fails
open on read or parse errors.
"""
from __future__ import annotations

import json
import sys

from detect import evaluate


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"unverified-tag-ledger: unreadable payload, allowing: {exc!r}\n")
        return
    try:
        verdict = evaluate(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"unverified-tag-ledger: detector error, allowing this reply: {exc!r}\n")
        return
    if verdict["block"]:
        sys.stderr.write(verdict["block"] + "\n")
        sys.exit(2)
    if verdict["note"]:
        sys.stderr.write(verdict["note"] + "\n")


if __name__ == "__main__":
    main()
