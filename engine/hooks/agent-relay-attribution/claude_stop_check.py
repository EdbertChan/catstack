#!/usr/bin/env python3
"""Claude Code Stop hook (advisory): when a subagent result arrived within
the last three turns and the reply states facts without attributing them
to the agent or re-verifying, emit a note. Never blocks: exit 0, the note
goes to stderr and to the harness as a systemMessage. Fails open.
"""
from __future__ import annotations

import json
import sys

from detect import decide


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    try:
        message = decide(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        sys.stderr.write(f"agent-relay-attribution: detector error, skipping: {exc!r}\n")
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    main()
