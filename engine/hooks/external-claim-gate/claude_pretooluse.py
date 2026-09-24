#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect, unreadable_payload  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "external-claim-gate",
        "claude",
        detect,
        "PreToolUse",
        unreadable_payload=unreadable_payload,
    )


if __name__ == "__main__":
    main()
