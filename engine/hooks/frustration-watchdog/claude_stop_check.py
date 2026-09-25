#!/usr/bin/env python3
"""Claude Code Stop entrypoint for frustration-watchdog."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook("frustration-watchdog", "claude", detect, "Stop")


if __name__ == "__main__":
    main()
