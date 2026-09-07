#!/usr/bin/env python3
"""Claude Code Stop hook: once catstack's own diff is stable across two
consecutive Stop calls (not mid-edit), tell the agent to open a PR for it.

Debounced -- see detect.py's decide(). Fail-open.

SubagentStop opt-out (see claude.hook.json `subagent_stop`): the PR
instruction belongs to the session owner. A subagent's payload shares the
parent's cwd, so firing here would consume the once-per-diff marker and the
parent would never be told. A payload carrying `agent_id` returns early.
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
    if isinstance(payload, dict) and payload.get("agent_id"):
        return
    try:
        message = decide(
            payload if isinstance(payload, dict) else {},
            deliver=False,
            debounce=True,
        )
    except Exception:
        return
    if not message:
        return
    sys.stderr.write(message + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
