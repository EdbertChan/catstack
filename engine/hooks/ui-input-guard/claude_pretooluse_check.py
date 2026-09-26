#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): block synthetic keyboard, mouse, and
screen-capture commands aimed at the user's live session unless a hands-off
window is open, the screen is unlocked, and the user is idle. Exit 2 blocks;
any error fails open.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook(
            "ui-input-guard",
            "claude",
            detect,
            "PreToolUse",
            json_error_stderr=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
