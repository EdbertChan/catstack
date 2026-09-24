#!/usr/bin/env python3
"""Claude Code PreToolUse entrypoint for pr-schema-gate."""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def _tool_name(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or payload.get("name")
        or ""
    )


def _json_error_message(exc: BaseException) -> str:
    return f"pr-schema-gate: unreadable hook payload, nothing checked: {exc}"


def main() -> None:
    raw = sys.stdin.read()
    sys.stdin = io.StringIO(raw)
    harness = "claude" if _tool_name(raw) == "Bash" else "codex"
    hook_event_name = "PreToolUse" if harness == "claude" else "Notify"
    try:
        run_hook(
            "pr-schema-gate",
            harness,
            detect,
            hook_event_name,
            json_error_message=_json_error_message,
            json_error_stderr=False,
            warn_stderr=True,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
