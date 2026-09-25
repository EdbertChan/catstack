#!/usr/bin/env python3
"""Claude Stop hook: note a verifier that passed earlier and failed later.

Advisory — stderr plus exit 0 — because a gate can legitimately start failing
when the turn broke it on purpose. Fail-open on any read/parse error.
"""
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
            "verdict-flip-watch",
            "claude",
            detect,
            "Stop",
            report_payload_errors=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
