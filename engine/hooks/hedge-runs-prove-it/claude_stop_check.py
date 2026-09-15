#!/usr/bin/env python3
"""Claude Code Stop hook entrypoint for hedge-runs-prove-it."""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    event = payload if isinstance(payload, dict) else {}
    if not any(event.get(key) for key in ("hook_event_name", "hookEventName", "event")):
        event["hook_event_name"] = "Stop"
    original_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(event))
        run_hook("hedge-runs-prove-it", "claude", detect)
    finally:
        sys.stdin = original_stdin


if __name__ == "__main__":
    main()
