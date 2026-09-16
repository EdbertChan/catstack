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
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps({"decision": "allow"}))
        return 0
    decision = decide(payload)
    outcome = decision.get("outcome")
    if outcome == "rewrite":
        print(
            json.dumps(
                {
                    "decision": "allow",
                    "updatedInput": updated_tool_input(payload, decision["wrapped_command"]),
                }
            )
        )
        return 0
    if outcome == "deny":
        reason = decision.get("reason", "bound-tool-result deny")
        print(json.dumps({"decision": "deny", "reason": reason, "message": reason}))
        return 0
    print(json.dumps({"decision": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
