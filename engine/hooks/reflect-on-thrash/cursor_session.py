#!/usr/bin/env python3
"""Cursor stop / sessionEnd hook entrypoint for reflect-on-thrash."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect as detect_reflect_on_thrash  # noqa: E402
from runtime import run_hook  # noqa: E402


def _event_name() -> str:
    args = {str(item).lower() for item in sys.argv[1:]}
    if args.intersection({"sessionend", "session_end"}):
        return "sessionEnd"
    return "stop"


def _detect(event: dict[str, object]):
    if _event_name() == "sessionEnd":
        event = dict(event)
        event["hook_event_name"] = "sessionEnd"
    return detect_reflect_on_thrash(event)


def main() -> None:
    try:
        run_hook(
            "reflect-on-thrash",
            "cursor",
            _detect,
            "stop",
            json_error_stderr=False,
            silent_output={"followup_message": ""},
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
