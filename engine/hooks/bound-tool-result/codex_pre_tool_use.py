#!/usr/bin/env python3
"""Codex PreToolUse: rewrite shell exec into capture_tool_result wrapper."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect import decide, updated_tool_input  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        print(
            f"bound-tool-result: could not read hook input ({type(exc).__name__}: {exc}); allowing unwrapped",
            file=sys.stderr,
        )
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = decide(payload)
    outcome = decision.get("outcome")
    if outcome == "rewrite":
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": updated_tool_input(payload, decision["wrapped_command"]),
                    }
                }
            )
        )
        return 0
    if outcome == "deny":
        reason = decision.get("reason", "bound-tool-result deny")
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
