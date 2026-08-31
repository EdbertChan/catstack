#!/usr/bin/env python3
"""Claude Code PostToolUse: inject once after four distinct file mutations.

Fail-open. Never denies.
"""
from __future__ import annotations

import json
import sys

from detect import record_file_mutation, reminder_text, should_inject_for_edits


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        record_file_mutation(payload if isinstance(payload, dict) else {})
        if not should_inject_for_edits(payload):
            return
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": reminder_text(),
                    }
                }
            )
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
