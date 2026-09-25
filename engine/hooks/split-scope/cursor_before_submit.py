#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt entrypoint for split-scope reminders."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect_cursor_before_submit  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "split-scope",
        "cursor",
        detect_cursor_before_submit,
        fail_open_context="cursor_before_submit",
    )


if __name__ == "__main__":
    main()
