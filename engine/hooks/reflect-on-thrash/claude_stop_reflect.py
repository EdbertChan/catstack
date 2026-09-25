#!/usr/bin/env python3
"""Claude Code Stop hook: defer ordinary thrash; inject on intervention.

The detector decides whether this turn should produce a reflect finding.
The shared runtime applies the registry mode, writes event rows, and renders
the harness response. Ordinary thrash still records a deferred marker inside
the detector so in-progress work is not stolen. Fail-open.
"""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
sys.path.insert(0, SDK_DIR)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "reflect-on-thrash",
        "claude",
        detect,
        hook_event_name="Stop",
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
