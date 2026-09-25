#!/usr/bin/env python3
"""Claude UserPromptSubmit entrypoint for hook-freshness."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook("hook-freshness", "claude", detect, "UserPromptSubmit", json_error_stderr=False)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise


if __name__ == "__main__":
    main()
