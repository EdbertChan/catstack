from __future__ import annotations

import json
import sys


def payload(harness: str, event: str, message: str) -> dict:
    if harness == "cursor":
        return {"additional_context": message}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def main() -> int:
    harness, event, form, message = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    sys.stdin.buffer.read()
    sys.stderr.write(f"fixture-context: {message}\n")
    if form == "text":
        sys.stdout.write(message + "\n")
        return 0
    sys.stdout.write(json.dumps(payload(harness, event, message)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
