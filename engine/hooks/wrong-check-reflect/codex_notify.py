#!/usr/bin/env python3
"""Codex `notify` hook: advisory wrong-check admission heads-up.

Codex fires notify after the turn is over — no way to block or force a
rewrite. Print a heads-up; chain to any prior notify command.

    notify = ["python3", "/path/to/codex_notify.py", "/path/to/old-notify", ...]
"""
from __future__ import annotations

import json
import subprocess
import sys

from detect import CODEX_ADVISORY, find_admission


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

    message = payload.get("last-assistant-message") or ""
    match = find_admission(message)
    if match:
        print(CODEX_ADVISORY.format(match=match), file=sys.stderr)


if __name__ == "__main__":
    main()
