#!/usr/bin/env python3
"""Claude Code PreToolUse hook for scratchpad-collision."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect
from runtime import run_hook


def main() -> None:
    try:
        run_hook(
            "scratchpad-collision",
            "claude",
            detect,
            hook_event_name="PreToolUse",
            json_error_stderr=False,
        )
    except SystemExit as exc:
        if exc.code:
            raise


if __name__ == "__main__":
    main()
