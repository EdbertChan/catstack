#!/usr/bin/env python3
"""Claude PreToolUse: refuse `git revert` until the session has read the
change being reversed and searched the history around the code it conflicts
with. Exits 2 with the missing steps on stderr. Fails open, with an
UNCHECKED note, when the payload or transcript cannot be read.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import SHELL_LIKE_TOOL_NAMES, decide


def _tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"history-before-reversal: UNCHECKED, payload is not JSON ({exc}); allowing.\n")
        return
    if not isinstance(payload, dict) or _tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
        return
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return
    try:
        verdict = decide(command, payload.get("transcript_path"))
    except Exception as exc:
        sys.stderr.write(f"history-before-reversal: detector error, allowing this command: {exc!r}\n")
        return
    if verdict.outcome == "block":
        sys.stderr.write(verdict.message + "\n")
        sys.exit(2)
    if verdict.outcome == "unchecked":
        sys.stderr.write(verdict.message + "\n")


if __name__ == "__main__":
    main()
