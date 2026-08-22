#!/usr/bin/env python3
"""Claude Code UserPromptSubmit: inject how-we-got-here + leak checklist on bug complaints.

Fail-open. No LLM. Does not run git.
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
        return
    try:
        prompt = extract_prompt_text(payload)
        if not is_bug_complaint(prompt):
            return
        checklist = build_checklist(prompt)
        quotes = extract_quoted_symptoms(prompt)
        remember_bug_complaint(payload, prompt, quotes, checklist)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": checklist,
                    }
                }
            )
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
