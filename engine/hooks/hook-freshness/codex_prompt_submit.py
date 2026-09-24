#!/usr/bin/env python3
"""Codex UserPromptSubmit entrypoint for hook-freshness."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect
from runtime import run_hook


def main() -> int:
    try:
        run_hook("hook-freshness", "codex", detect, "UserPromptSubmit", json_error_stderr=False)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
