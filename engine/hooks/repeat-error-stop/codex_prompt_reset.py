#!/usr/bin/env python3
"""Codex UserPromptSubmit: a new human prompt resets the repeat-error counters."""
from __future__ import annotations

import json
import sys

from detect import handle_prompt


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        handle_prompt(payload if isinstance(payload, dict) else {})
    except Exception:
        return


if __name__ == "__main__":
    main()
