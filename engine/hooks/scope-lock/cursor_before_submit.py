#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt hook: persist scope corrections."""
from __future__ import annotations

import json
import sys

from detect import process_prompt


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        process_prompt(payload if isinstance(payload, dict) else {})
    except Exception:
        pass
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
