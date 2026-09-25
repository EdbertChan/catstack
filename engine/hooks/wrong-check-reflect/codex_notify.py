#!/usr/bin/env python3
"""Codex notify hook for wrong-check-reflect."""
from __future__ import annotations

import io
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

    previous_stdin = sys.stdin
    sys.stdin = io.StringIO(raw)
    try:
        run_hook(
            "wrong-check-reflect",
            "codex",
            detect,
            "Notify",
            report_payload_errors=False,
        )
    finally:
        sys.stdin = previous_stdin


if __name__ == "__main__":
    main()
