#!/usr/bin/env python3
"""Codex PreToolUse hook: route no-comments findings through the SDK."""
from __future__ import annotations

import sys
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

from detect import detect
from runtime import run_hook


def main() -> None:
    try:
        run_hook("no-comments", "codex", detect, hook_event_name="PreToolUse")
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
