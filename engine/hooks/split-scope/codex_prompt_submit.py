#!/usr/bin/env python3
"""Codex UserPromptSubmit entrypoint for split-scope."""
from __future__ import annotations

import json
import sys

from detect import extract_prompt_text, plans_multi_slice_work, reminder_text


def _log(context: str, exc: Exception) -> None:
    sys.stderr.write(f"split-scope codex_prompt_submit: {context}: {exc}\n")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        _log("unreadable hook input", exc)
        return
    try:
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
        _log("detector failed", exc)


if __name__ == "__main__":
    main()
