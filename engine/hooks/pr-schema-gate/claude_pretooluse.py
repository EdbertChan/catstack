#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: block `gh pr create` / `gh pr edit --body*`.

Fail-open on any parse error or when the repo has no scripts/create-pr.mjs
(no sanctioned tool to redirect to). See detect.py for the full rationale.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import (
    block_message_for,
    effective_start_dir,
    find_blocked_command,
    repo_root_with_create_pr_tool,
)


def _tool_name(payload: dict) -> str:
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or payload.get("name")
        or ""
    )


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


SHELL_LIKE_TOOL_NAMES = (
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
)


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    try:
        # Positive-list only: an unnamed/unknown tool_name must NOT fall
        # through to matching, or a Write/Edit call whose file content merely
        # mentions "gh pr create" (e.g. this hook's own detect.py) would be
        # blocked as if it were a shell execution.
        name = _tool_name(payload)
        if name not in SHELL_LIKE_TOOL_NAMES:
            return

        cwd = payload.get("cwd") or os.getcwd()
        command = str(_tool_input(payload).get("command") or "")
        cwd = effective_start_dir(cwd, command)
        if repo_root_with_create_pr_tool(cwd) is None:
            return

        cmd = find_blocked_command(raw)
        if cmd is None:
            return

        sys.stderr.write(block_message_for(cmd) + "\n")
        sys.exit(2)
    except Exception:
        return


if __name__ == "__main__":
    main()
