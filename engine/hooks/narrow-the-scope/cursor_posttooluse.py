#!/usr/bin/env python3
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
        "narrow-the-scope",
        "cursor",
        detect,
        hook_event_name="postToolUse",
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
