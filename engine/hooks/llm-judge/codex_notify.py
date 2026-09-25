#!/usr/bin/env python3
from __future__ import annotations

import io
import subprocess
import sys

import entrypoint


def main() -> None:
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]

    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"llm-judge: chained notify failed: {exc}", file=sys.stderr)

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(raw)
    try:
        entrypoint.run(
            "codex",
            "Notify",
            "llm-judge: could not read the Codex notify payload",
        )
    finally:
        sys.stdin = old_stdin


if __name__ == "__main__":
    main()
