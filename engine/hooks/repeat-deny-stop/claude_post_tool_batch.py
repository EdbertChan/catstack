#!/usr/bin/env python3
"""Claude Code PostToolBatch hook for repeat-deny-stop."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect
from runtime import run_hook


def main() -> None:
    run_hook(
        "repeat-deny-stop",
        "claude",
        detect,
        hook_event_name="PostToolBatch",
        json_error_stderr_prefix="repeat-deny-stop: unreadable hook input, skipping",
    )


if __name__ == "__main__":
    main()
