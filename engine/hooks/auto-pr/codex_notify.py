#!/usr/bin/env python3
"""Codex turn-complete notifier for catstack's read-only auto-PR detector.

Codex notify runs after the turn and cannot force a rewrite. Emit the same
catstack-scoped instruction used by the blocking harness hooks so the next
turn cannot silently leave shippable repository changes unpublished. Chain
any notifier that was already configured.
"""
from __future__ import annotations

import json
from io import StringIO
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


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
        event = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict) or event.get("type") != "agent-turn-complete":
        return
    previous_stdin = sys.stdin
    sys.stdin = StringIO(raw)
    try:
        run_hook("auto-pr", "codex", detect)
    finally:
        sys.stdin = previous_stdin


if __name__ == "__main__":
    main()
