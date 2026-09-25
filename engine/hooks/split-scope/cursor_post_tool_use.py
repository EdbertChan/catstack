#!/usr/bin/env python3
"""Cursor postToolUse entrypoint for split-scope reminders."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect_cursor_post_tool_use  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "split-scope",
        "cursor",
        detect_cursor_post_tool_use,
        "postToolUse",
        fail_open_context="cursor_post_tool_use",
    )


if __name__ == "__main__":
    main()
