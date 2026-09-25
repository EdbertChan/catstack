#!/usr/bin/env python3
"""Cursor stop / sessionEnd for reflect-on-thrash.

`stop` (mid-turn) records a deferred marker for ordinary thrash — empty
followup_message so the current task is not stolen. Same-type user
intervention delivers immediately through the shared runtime. `sessionEnd`
delivers any leftover deferred reflect prompt. Fail-open. Pass `sessionEnd`
as argv from the sessionEnd hook entry.
"""
from __future__ import annotations

import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
sys.path.insert(0, SDK_DIR)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def _event_name(argv: list[str]) -> str:
    lowered = {item.lower() for item in argv}
    if lowered & {"sessionend", "session_end"}:
        return "sessionEnd"
    return "stop"


def main() -> None:
    run_hook(
        "reflect-on-thrash",
        "cursor",
        detect,
        hook_event_name=_event_name(sys.argv[1:]),
        json_error_stderr=False,
    )


if __name__ == "__main__":
    main()
