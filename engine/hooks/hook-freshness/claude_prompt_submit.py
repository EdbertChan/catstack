#!/usr/bin/env python3
"""Claude Code UserPromptSubmit: warn once per session when the catstack
checkout behind ~/.claude/hooks is off main or behind origin/main, so merged
hook fixes that are not live here get noticed. Advisory, fail-open, no block.
"""
from __future__ import annotations

import json
import sys

from detect import decide_json


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        out = decide_json(payload if isinstance(payload, dict) else {})
    except Exception:
        return
    if out:
        print(out)


if __name__ == "__main__":
    main()
