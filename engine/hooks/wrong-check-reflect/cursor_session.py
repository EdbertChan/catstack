#!/usr/bin/env python3
"""Cursor stop / sessionEnd for wrong-check-reflect.

`stop` delivers followup_message when the last assistant message admits a
prior check was wrong. `sessionEnd` stays silent if already prompted.
Fail-open. When the regex stays silent, ask the background llm-judge instead;
its verdict arrives on the next turn.
"""
from __future__ import annotations

import json
import sys

from detect import decide, try_enqueue_judge


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"followup_message": ""}))
        return
    payload = payload if isinstance(payload, dict) else {}
    try:
        message = decide(payload)
    except Exception:
        print(json.dumps({"followup_message": ""}))
        return
    try_enqueue_judge(payload, bool(message))
    print(json.dumps({"followup_message": message or ""}))


if __name__ == "__main__":
    main()
