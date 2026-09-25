#!/usr/bin/env python3
"""Claude Code Stop hook for prove-it-ship-gate."""
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
            "prove-it-ship-gate",
            "claude",
            detect,
            "Stop",
            json_error_stderr=False,
        )
    except SystemExit as exc:
        if exc.code == 0:
            return
        raise


if __name__ == "__main__":
    main()
