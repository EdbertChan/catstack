#!/usr/bin/env python3
"""Codex turn-complete notifier for catstack's read-only auto-PR detector.

Codex notify runs after the turn and cannot force a rewrite. Emit the same
catstack-scoped instruction used by the blocking harness hooks so the next
turn cannot silently leave shippable repository changes unpublished. Chain
any notifier that was already configured.
"""
from __future__ import annotations

import json
import subprocess
import sys

import detect


def main() -> None:
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]

    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"auto-pr: chained notify failed: {exc}", file=sys.stderr)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if payload.get("type") != "agent-turn-complete":
        return

    instruction = detect.decide(payload, deliver=True)
    if instruction:
        print(
            "auto-pr: the turn ended with shippable catstack changes. "
            f"On the next turn, complete this before other work: {instruction}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
