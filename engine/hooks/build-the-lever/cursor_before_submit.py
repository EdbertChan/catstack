#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt: remember bulk work for the next postToolUse inject.

Cursor cannot inject context here. Always continue. Fail-open.
"""
from __future__ import annotations

import json
import sys

from detect import extract_prompt_text, is_bulk_work, remember_bulk_prompt


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"continue": True}))
        return
    try:
        if is_bulk_work(extract_prompt_text(payload if isinstance(payload, dict) else {})):
            remember_bulk_prompt(payload)
        print(json.dumps({"continue": True}))
    except Exception:
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
