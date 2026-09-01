#!/usr/bin/env python3
"""Cursor postToolUse: inject pending prompt reminder or four-edit reminder once.

Fail-open. Never continue false.
"""
from __future__ import annotations

import json
import sys

from detect import (
    consume_prompt_pending,
    record_file_mutation,
    reminder_text,
    should_inject_for_edits,
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        record_file_mutation(payload if isinstance(payload, dict) else {})
        if consume_prompt_pending(payload) or should_inject_for_edits(payload):
            print(json.dumps({"additional_context": reminder_text()}))
    except Exception:
        return


if __name__ == "__main__":
    main()
