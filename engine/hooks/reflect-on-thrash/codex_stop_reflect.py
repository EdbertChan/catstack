#!/usr/bin/env python3
"""Codex Stop hook for reflect-on-thrash."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
sys.path.insert(0, SDK_DIR)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "reflect-on-thrash",
        "codex",
        detect,
        hook_event_name="Stop",
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
