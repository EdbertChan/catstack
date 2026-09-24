#!/usr/bin/env python3
"""Claude Code Stop hook for prove-it-ship-gate."""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    raw = sys.stdin.read()
    try:
        json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return
    sys.stdin = io.StringIO(raw)
    run_hook(
        "prove-it-ship-gate",
        "claude",
        detect,
        hook_event_name="Stop",
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
