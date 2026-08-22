#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt: remember bug-complaint checklist for later inject.

Cursor's beforeSubmitPrompt schema is continue/user_message only; injection
happens on the next postToolUse via cursor_post_tool_use.py. Fail-open.
"""
from __future__ import annotations

import json
import sys

from detect import build_checklist, extract_prompt_text, extract_quoted_symptoms, is_bug_complaint
from state import remember_bug_complaint


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"continue": True}))
        return
    try:
        prompt = extract_prompt_text(payload)
        if is_bug_complaint(prompt):
            checklist = build_checklist(prompt)
            quotes = extract_quoted_symptoms(prompt)
            remember_bug_complaint(payload, prompt, quotes, checklist)
        print(json.dumps({"continue": True}))
    except Exception:
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
