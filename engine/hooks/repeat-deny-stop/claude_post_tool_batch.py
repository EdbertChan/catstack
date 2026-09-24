#!/usr/bin/env python3
"""Claude Code PostToolBatch hook for repeat-deny-stop."""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect, unchecked_stderr
from runtime import run_hook


def _json_error_message(exc: BaseException) -> str:
    return f"repeat-deny-stop: unreadable hook input, skipping: {exc!r}"


def main() -> None:
    run_hook(
        "repeat-deny-stop",
        "claude",
        detect,
        hook_event_name="PostToolBatch",
        json_error_message=_json_error_message,
        post_detect_stderr=unchecked_stderr,
    )


if __name__ == "__main__":
    main()
