#!/usr/bin/env python3
"""Cursor stop / sessionEnd hook for wrong-check-reflect."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402

def main() -> None:
    try:
        run_hook(
            "wrong-check-reflect",
            "cursor",
            detect,
            "stop",
            fail_open_context="cursor_session",
            quiet_payload_errors=True,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
