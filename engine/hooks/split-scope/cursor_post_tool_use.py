#!/usr/bin/env python3
"""Cursor postToolUse entrypoint for split-scope."""
from __future__ import annotations

import json
import sys

from detect import consume_prompt_pending, reminder_text


def _log(context: str, exc: Exception) -> None:
    sys.stderr.write(f"split-scope cursor_post_tool_use: {context}: {exc}\n")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        _log("unreadable hook input", exc)
        return
    try:
        if not isinstance(payload, dict):
            return
        if consume_prompt_pending(payload):
            print(json.dumps({"additional_context": reminder_text()}))
    except Exception as exc:
        _log("state read failed", exc)


if __name__ == "__main__":
    main()
