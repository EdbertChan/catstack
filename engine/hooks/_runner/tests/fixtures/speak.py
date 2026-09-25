"""Fixture hook: prints the engine/hooks/_sdk/render.py output shape for one
harness and one verdict, so a test can drive the same script through run.py
alone and through dispatch.py and compare the two contracts."""
from __future__ import annotations

import json
import sys

MESSAGE = "fixture hook spoke"

SPEAK = {
    "claude": {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": MESSAGE}},
    "cursor": {"additional_context": MESSAGE},
    "codex": {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": MESSAGE}},
}

BLOCK = {
    "cursor": {"continue": False, "permission": "deny", "user_message": MESSAGE},
    "codex": {
        "decision": "block",
        "reason": MESSAGE,
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": MESSAGE},
    },
}


def main() -> int:
    harness, verdict = sys.argv[1], sys.argv[2]
    sys.stdin.buffer.read()
    sys.stderr.write(f"fixture-extra-manifest: {harness} {verdict}\n")
    if verdict == "block" and harness == "claude":
        sys.stderr.write(MESSAGE + "\n")
        return 2
    sys.stdout.write(json.dumps(BLOCK[harness] if verdict == "block" else SPEAK[harness]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
