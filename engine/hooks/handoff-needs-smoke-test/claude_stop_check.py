#!/usr/bin/env python3
"""Claude Code Stop hook: block a reply that hands the user a script this
session never ran, unless the reply names why the run cannot happen here.
Fails open on read or parse errors; `stop_hook_active` skips.
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
        run_hook("handoff-needs-smoke-test", "claude", detect, "Stop", json_error_stderr=False)
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
