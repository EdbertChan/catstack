#!/usr/bin/env python3
"""Claude Code Stop hook: untracked files this turn left at the repo root or
under scripts/ must be named in the reply. Blocks with exit 2; fails open
on read, parse, or git errors; `stop_hook_active` skips.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook(
            "new-file-callout",
            "claude",
            detect,
            hook_event_name="Stop",
            json_error_stderr=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
