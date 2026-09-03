#!/usr/bin/env python3
"""Claude/Cursor PreToolUse: block `gh pr create` / `gh pr edit --body*`,
and require the sanctioned create-pr.mjs follow-up between branch publications.

Fail-open on any parse error, on malformed pending state, or when the repo has
no scripts/create-pr.mjs (no sanctioned tool to redirect to). See detect.py for
the full rationale.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import (
    block_message_for,
    clear_pending,
    effective_tool_start_dir,
    find_blocked_command,
    find_publication_command,
    followup_required_message,
    is_sanctioned_followup,
    mark_pending,
    read_pending,
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
    """Evaluate one PreToolUse payload, in a deliberate order.

    The direct-writer block runs first, so the follow-up bookkeeping can
    never soften it: a command that both mentions create-pr.mjs and writes a
    body directly is still a direct write. Then the sanctioned create-pr.mjs
    path clears any owed follow-up. Then a publication action is blocked if a
    follow-up is already owed, and otherwise allowed while arming one.
    Anything else is an unrelated command: allowed, and deliberately leaving
    state untouched, so an owed follow-up survives the greps and builds that
    happen between a push and its create-pr.mjs run.
    """
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
        cwd = effective_tool_start_dir(cwd, _tool_input(payload))
        repo_root = repo_root_with_create_pr_tool(cwd)
        if repo_root is None:
            return

        cmd = find_blocked_command(raw)
        if cmd is not None:
            sys.stderr.write(block_message_for(cmd) + "\n")
            sys.exit(2)

        if is_sanctioned_followup(raw):
            clear_pending(repo_root)
            return

        published = find_publication_command(raw)
        if published is None:
            return

        if read_pending(repo_root) is not None:
            sys.stderr.write(followup_required_message(published) + "\n")
            sys.exit(2)

        mark_pending(repo_root)
    except Exception:
        return


if __name__ == "__main__":
    main()
