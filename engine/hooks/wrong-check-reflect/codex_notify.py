#!/usr/bin/env python3
"""Codex notify hook for wrong-check-reflect."""
from __future__ import annotations

import json
import subprocess
import sys

from detect import try_enqueue_judge


def main() -> None:
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]

    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"wrong-check-reflect: chained notify failed: {exc}", file=sys.stderr)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    if payload.get("type") != "agent-turn-complete":
        return

    try_enqueue_judge(payload)


if __name__ == "__main__":
    main()
