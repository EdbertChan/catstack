#!/usr/bin/env python3
from __future__ import annotations

from functools import partial
import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import bad_payload_findings, bad_payload_message, detect, diagnostic  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "skill-usage-log",
        "claude",
        partial(detect, harness="claude", kind="tool"),
        "PreToolUse",
        json_error_detect=bad_payload_findings,
        json_error_message=bad_payload_message,
        post_detect_stderr=diagnostic,
    )

if __name__ == "__main__":
    main()
