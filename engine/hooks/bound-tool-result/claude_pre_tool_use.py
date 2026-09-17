#!/usr/bin/env python3
"""Claude Code PreToolUse: rewrite Bash into capture_tool_result wrapper."""
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
        print(json.dumps({"continue": True}))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps({"continue": True}))
        return 0
    decision = decide(payload)
    outcome = decision.get("outcome")
    if outcome == "rewrite":
        print(
            json.dumps(
                {
                    "continue": True,
                    "updatedInput": updated_tool_input(payload, decision["wrapped_command"]),
                }
            )
        )
        return 0
    if outcome == "deny":
        print(
            json.dumps(
                {
                    "continue": False,
                    "decision": "block",
                    "reason": decision.get("reason", "bound-tool-result deny"),
                    "systemMessage": decision.get("reason", "bound-tool-result deny"),
                }
            )
        )
        return 0
    print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
