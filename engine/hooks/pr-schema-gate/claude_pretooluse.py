#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
for path in (HERE, SDK_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def _claude_detect(event: dict[str, object]):
    findings = detect(event)
    tool_name = str(event.get("tool_name") or event.get("toolName") or event.get("tool") or event.get("name") or "")
    if tool_name and tool_name != "Bash":
        return []
    return findings


def main() -> None:
    try:
        run_hook(
            "pr-schema-gate",
            "claude",
            _claude_detect,
            hook_event_name="PreToolUse",
            json_error_stderr_prefix="pr-schema-gate: unreadable hook payload, nothing checked",
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
