#!/usr/bin/env python3
"""Claude Code Stop hook for restart-risk-check."""
from __future__ import annotations

from pathlib import Path
import sys

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
if SDK_DIR.exists():
    sys.path.insert(0, str(SDK_DIR))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook(
            "restart-risk-check",
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
