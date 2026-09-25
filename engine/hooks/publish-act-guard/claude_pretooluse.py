#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: refuse a publishing command issued from inside a
subagent while a live Invoker owner is reachable.

The shared hook runtime applies publish-act-guard's registry mode, writes
metrics rows, and renders the Claude response.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK_DIR = HERE.parent / "_sdk"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SDK_DIR))

from detect import detect
from runtime import run_hook


def main() -> None:
    run_hook(
        "publish-act-guard",
        "claude",
        detect,
        hook_event_name="PreToolUse",
        json_error_stderr_prefix="publish-act-guard: payload did not parse",
    )


if __name__ == "__main__":
    main()
