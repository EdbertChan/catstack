from __future__ import annotations

import json
import sys

UPDATED_INPUT = {"command": "echo safe"}

JSON_BLOCK = {
    "claude": {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "",
            "updatedInput": UPDATED_INPUT,
        }
    },
    "codex": {"decision": "block", "reason": ""},
    "cursor": {"continue": False, "permission": "deny", "user_message": "", "agent_message": ""},
}


def payload(harness: str, message: str) -> dict:
    shaped = json.loads(json.dumps(JSON_BLOCK[harness]))
    target = shaped.get("hookSpecificOutput", shaped)
    for key in ("permissionDecisionReason", "reason", "user_message", "agent_message"):
        if key in target:
            target[key] = message
    return shaped


def main() -> int:
    harness, form, message = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.stdin.buffer.read()
    if form == "exit2":
        sys.stderr.write(message + "\n")
        return 2
    sys.stdout.write(json.dumps(payload(harness, message)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
