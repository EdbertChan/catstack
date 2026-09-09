#!/usr/bin/env python3
"""PreToolUse: block a PR publication carrying unsourced repo-history claims."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect import decide  # noqa: E402

SHELL_LIKE = {"Bash", "bash", "shell", "Shell", "exec", "exec_command",
              "run_terminal_cmd", "local_shell", "run_command", "shell_call"}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        name = payload.get("tool_name") or payload.get("toolName") or ""
        if name not in SHELL_LIKE:
            return
        ti = payload.get("tool_input") or payload.get("toolInput") or {}
        command = ti.get("command") or ""
        message = decide(command, payload.get("cwd"))
    except Exception as exc:
        sys.stderr.write(f"history-claim-check: detector error, allowing: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
