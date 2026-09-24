#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: refuse `gh pr edit` (broken on every flag) and
refuse a state-changing command whose stdout and stderr are both discarded
with no exit-code check, and one whose exit code a pipe replaces. Exits 2
with the redirect on stderr; a command the pipe check cannot lex is allowed
and reported as unchecked on stderr.

Positive-lists shell-like tool names, so a Write/Edit whose *content*
mentions these shapes is never blocked. Fails open on any parse error.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import piped_away_mutations, piped_message, pretooluse_problems, shell_dialect

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
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(payload, dict):
        return
    try:
        if _tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
            return
        problems = pretooluse_problems(raw)
        tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
        command = tool_input.get("command") or tool_input.get("cmd") if isinstance(tool_input, dict) else None
        if isinstance(command, str):
            scan = piped_away_mutations(command, shell_dialect(os.environ))
            if scan.hits:
                problems.append(piped_message(scan))
            for reason in scan.unchecked:
                sys.stderr.write(f"gh-write-verification: pipe exit-code check unchecked, allowing: {reason}\n")
        else:
            sys.stderr.write("gh-write-verification: pipe exit-code check unchecked, allowing: no command string in tool_input\n")
    except Exception as exc:
        sys.stderr.write(f"gh-write-verification: detector error, allowing this command: {exc!r}\n")
        return
    if not problems:
        return
    sys.stderr.write("\n\n".join(problems) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
