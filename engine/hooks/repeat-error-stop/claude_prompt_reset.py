#!/usr/bin/env python3
"""Claude UserPromptSubmit: a new human prompt resets the repeat-error counters."""
from __future__ import annotations

import json
import sys

from detect import handle_prompt


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        handle_prompt(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        print(f"catstack-hook-error repeat-error-stop: {type(exc).__name__}: {exc}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
