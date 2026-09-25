#!/usr/bin/env python3
"""Claude Stop entrypoint for gh-write-verification."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SDK_DIR, "_sdk"))

from detect import detect
from runtime import run_hook


def main() -> None:
    run_hook("gh-write-verification", "claude", detect, hook_event_name="Stop")


if __name__ == "__main__":
    main()
