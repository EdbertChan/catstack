#!/usr/bin/env python3
"""Claude Code Stop hook for incidence-needs-repetition."""
from __future__ import annotations

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
    run_hook("incidence-needs-repetition", "claude", detect, "Stop")


if __name__ == "__main__":
    main()
