#!/usr/bin/env python3
"""Claude PreToolUse on Bash: block a status-narrowed mutation of a target the
live human turn quantified with all / every / each. Exits 2 with the reason on
stderr for HIT and for UNCHECKED; exits 0 for CLEAN.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import CLEAN, decide_payload

SHELL_LIKE_TOOL_NAMES = (
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
)


def _tool_name(payload: dict) -> str:
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or payload.get("name")
        or ""
    )


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"categorical-scope-guard: hook payload is not JSON, nothing to classify: {exc}\n")
        return
    if not isinstance(payload, dict) or _tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
        return
    try:
        verdict = decide_payload(payload)
    except Exception as exc:
        sys.stderr.write(
            f"categorical-scope-guard: UNCHECKED -- the detector failed ({exc!r}) while classifying a "
            "status-filtered mutation. Blocked rather than passed; drop the status filter or rephrase the command.\n"
        )
        sys.exit(2)
    if verdict.outcome == CLEAN:
        return
    sys.stderr.write(verdict.message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
