#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect_codex_notify as detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def _json_error(exc: BaseException) -> str:
    return f"llm-judge: could not read the Codex notify payload: {exc}"


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

    original_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(raw)
        run_hook("llm-judge", "codex", detect, hook_event_name="Notify", json_error_message=_json_error)
    except SystemExit:
        if __name__ == "__main__":
            raise
    finally:
        sys.stdin = original_stdin


if __name__ == "__main__":
    main()
