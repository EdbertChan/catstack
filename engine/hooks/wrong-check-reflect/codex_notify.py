#!/usr/bin/env python3
"""Codex notify hook for wrong-check-reflect."""
from __future__ import annotations

import io
import json
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
            print(f"wrong-check-reflect: chained notify failed: {exc}", file=sys.stderr)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    if payload.get("type") != "agent-turn-complete":
        return

    sys.stdin = io.StringIO(raw)
    try:
        run_hook(
            "wrong-check-reflect",
            "codex",
            detect,
            "Notify",
            fail_open_context="codex_notify",
            quiet_payload_errors=True,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
