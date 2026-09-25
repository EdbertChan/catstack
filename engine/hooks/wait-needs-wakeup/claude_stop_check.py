#!/usr/bin/env python3
"""Claude Code Stop hook: a reply that says it is waiting / watching / will
report must name a clock-time ETA and have a scheduled wakeup in the turn.
Blocks with exit 2; fails open on any read or parse error;
`stop_hook_active` skips so the rewrite turn can finish.
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
            "Stop",
            report_payload_errors=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
