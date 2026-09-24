#!/usr/bin/env python3
"""Cursor preToolUse hook: enforce the current session's scope lock."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook("scope-lock", "cursor", detect, hook_event_name="preToolUse")


if __name__ == "__main__":
    main()
