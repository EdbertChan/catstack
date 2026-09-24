#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect, detect_json_error  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "external-claim-gate",
        "claude",
        detect,
        hook_event_name="PreToolUse",
        json_error_detect=detect_json_error,
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
