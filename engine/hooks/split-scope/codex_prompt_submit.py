#!/usr/bin/env python3
"""Codex UserPromptSubmit entrypoint for split-scope reminders."""
from __future__ import annotations

import json
import sys
import traceback

from detect import extract_prompt_text, plans_multi_slice_work, reminder_text


def _fail_open(context: str) -> None:
    print(f"split-scope codex_prompt_submit fail-open during {context}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        if not plans_multi_slice_work(extract_prompt_text(payload)):
            return
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
    except Exception as exc:
        print(f"catstack-hook-error split-scope: {type(exc).__name__}: {exc}", file=sys.stderr)
        _fail_open("prompt detection")


if __name__ == "__main__":
    main()
