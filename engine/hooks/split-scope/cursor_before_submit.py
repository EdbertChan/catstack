#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt entrypoint for split-scope reminders."""
from __future__ import annotations

import json
import sys
import traceback

from detect import extract_prompt_text, plans_multi_slice_work, remember_cursor_prompt


def _fail_open(context: str) -> None:
    print(f"split-scope cursor_before_submit fail-open during {context}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict) and plans_multi_slice_work(extract_prompt_text(payload)):
            remember_cursor_prompt(payload)
    except Exception as exc:
        print(f"catstack-hook-error split-scope: {type(exc).__name__}: {exc}", file=sys.stderr)
        _fail_open("prompt detection")


if __name__ == "__main__":
    main()
