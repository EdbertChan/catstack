#!/usr/bin/env python3
"""Claude Code PostToolBatch hook: when the same deny reason hits two tool
calls in a row, tell the model to stop calling tools and follow the deny
text. Never blocks: exit 0, the message goes to the model as
additionalContext. Fails open on any read or parse error, and says so on
stderr.
"""
from __future__ import annotations

import json
import sys

from detect import record_batch


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"repeat-deny-stop: unreadable hook input, skipping: {exc!r}\n")
        return
    try:
        message, unchecked = record_batch(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"repeat-deny-stop: detector error, skipping this batch: {exc!r}\n")
        return
    if unchecked:
        sys.stderr.write(
            f"repeat-deny-stop: {unchecked} tool call(s) in this batch had no readable result; "
            "left uncounted\n"
        )
    if not message:
        return
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "PostToolBatch", "additionalContext": message},
    }))


if __name__ == "__main__":
    main()
