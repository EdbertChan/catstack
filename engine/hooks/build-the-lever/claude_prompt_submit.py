#!/usr/bin/env python3
"""Claude Code UserPromptSubmit: inject build-the-lever on bulk work.

Fail-open. No LLM. Never denies.
"""
from __future__ import annotations

import json
import sys

from detect import extract_prompt_text, is_bulk_work, mark_injected, reminder_text


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        if not is_bulk_work(extract_prompt_text(payload if isinstance(payload, dict) else {})):
            return
        mark_injected(payload)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": reminder_text(),
                    }
                }
            )
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
