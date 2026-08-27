#!/usr/bin/env python3
"""Claude UserPromptSubmit hook: record corrections and inject the gate."""
from __future__ import annotations

import json
import sys

from detect import process_prompt, prompt_instruction


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        state = process_prompt(payload if isinstance(payload, dict) else {})
        instruction = prompt_instruction(state)
        if instruction:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": instruction,
                }
            }))
    except Exception:
        return


if __name__ == "__main__":
    main()
