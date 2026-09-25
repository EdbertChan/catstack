#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): block foreground poll loops and long
bare sleeps. The wait belongs to the harness (ScheduleWakeup / Monitor /
run_in_background that exits on the condition). Blocks with exit 2; fails
open on any read or parse error.
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
            "wait-needs-wakeup",
            "claude",
            detect,
            "PreToolUse",
            report_payload_errors=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
