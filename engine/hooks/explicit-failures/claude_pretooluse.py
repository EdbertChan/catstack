#!/usr/bin/env python3
"""Claude Code PreToolUse hook entrypoint for explicit-failures."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook("explicit-failures", "claude", detect, "PreToolUse", json_error_stderr=False, mirror_stderr=True)
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
