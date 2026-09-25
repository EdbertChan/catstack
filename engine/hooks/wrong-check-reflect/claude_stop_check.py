#!/usr/bin/env python3
"""Claude Code Stop hook for wrong-check-reflect."""
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
            "wrong-check-reflect",
            "claude",
            detect,
            "Stop",
            fail_open_context="claude_stop_check",
            quiet_payload_errors=True,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise

if __name__ == "__main__":
    main()
