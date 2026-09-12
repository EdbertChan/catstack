#!/usr/bin/env python3
"""Cursor postToolUse entrypoint for split-scope reminders."""
from __future__ import annotations

import json
import sys
import traceback

from detect import consume_cursor_prompt, reminder_text


def _fail_open(context: str) -> None:
    print(f"split-scope cursor_post_tool_use fail-open during {context}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        if consume_cursor_prompt(payload):
            print(json.dumps({"additional_context": reminder_text()}))
    except Exception as exc:
        print(f"catstack-hook-error split-scope: {type(exc).__name__}: {exc}", file=sys.stderr)
        _fail_open("pending reminder delivery")


if __name__ == "__main__":
    main()
