#!/usr/bin/env python3
"""Claude/Cursor/Codex PreToolUse: check direct PR text writes against the repo's
PR style and remind about the stack follow-up. Never blocks: exit 0 always.

Findings go to stderr for every harness, and to Claude as additionalContext
when the tool is Claude Code's `Bash`. See detect.py for the rules and
shell_model.py for how a tool call becomes commands.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect import (  # noqa: E402
    UNPARSEABLE_MESSAGE,
    check_body_file,
    classify_pr_text_write,
    clear_pending,
    followup_message,
    is_create_pr_followup,
    is_stack_push,
    mark_pending,
    read_pending,
    scope_root,
    style_message,
)
from shell_model import parse_commands, shell_call_from_tool_input  # noqa: E402

SHELL_LIKE_TOOL_NAMES = (
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
)
CLAUDE_SHELL_TOOL = "Bash"


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


def evaluate(payload: dict) -> list[str]:
    """Return the advisory lines for one tool call, in command order.

    Positive-list only: a Write/Edit call whose content mentions a PR command
    is file content, not a command, and is never evaluated.
    """
    if _tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
        return []
    session_cwd = str(payload.get("cwd") or os.getcwd())
    call = shell_call_from_tool_input(_tool_input(payload))
    if call is None:
        return []
    commands = parse_commands(call, session_cwd)
    if commands is None:
        base = call.workdir or session_cwd
        return [UNPARSEABLE_MESSAGE] if scope_root(base, None) else []

    messages: list[str] = []
    for command in commands:
        write = classify_pr_text_write(command)
        if write is not None:
            root = scope_root(write.cwd, write.repo_spec)
            if root is None:
                continue
            if write.body_ref and write.body_file is None:
                outcome, detail = "unchecked", (
                    f"the body file path {write.body_ref} uses a shell variable the hook cannot resolve"
                )
            else:
                outcome, detail = check_body_file(root, write.body_file, write.cwd)
            if outcome == "clean":
                clear_pending(root)
            message = style_message(outcome, detail, write.body_file)
            if message:
                messages.append(message)
            continue
        root = scope_root(command.cwd, None)
        if root is None:
            continue
        if is_create_pr_followup(command):
            clear_pending(root)
        elif is_stack_push(command):
            messages.append(followup_message(read_pending(root) is not None))
            mark_pending(root)
    return messages


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"pr-schema-gate: unreadable hook payload, nothing checked: {exc}\n")
        return
    if not isinstance(payload, dict):
        return
    try:
        messages = evaluate(payload)
    except Exception as exc:
        sys.stderr.write(f"pr-schema-gate: internal error, nothing checked: {exc!r}\n")
        return
    if not messages:
        return
    text = "\n\n".join(messages)
    sys.stderr.write(text + "\n")
    if _tool_name(payload) == CLAUDE_SHELL_TOOL:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}))


if __name__ == "__main__":
    main()
