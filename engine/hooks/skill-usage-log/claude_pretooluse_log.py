#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Skill): crude local usage logging, off by default.

Catstack has no mechanism anywhere that records which skill fires, when, or
how often -- "which skills are stale" can currently only be guessed from
`git log` / last-modified dates on skill files. This hook is the first
slice toward real data: append one JSON line per Skill invocation to a
local log file, gated behind an env var so it costs nothing when unset.

The write path is deliberately a single function, record_skill_usage().
Swapping local-file logging for a real metrics ingester later is a change
to that one function, not to the hook's read/gate/build logic around it.

Never blocks the Skill call and fails open on any error (env var unset,
malformed stdin, unwritable log dir): logging must never break the call.
"""
from __future__ import annotations

import json
import os
import sys
import time

ENABLED_ENV = "CATSTACK_SKILL_USAGE_LOG"
STATE_DIR = os.environ.get(
    "CATSTACK_SKILL_USAGE_LOG_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-skill-usage-log"),
)
LOG_FILE_NAME = "skill-usage.jsonl"


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "") == "1"


def _skill_name(tool_input: dict) -> str:
    value = tool_input.get("skill")
    return value.strip() if isinstance(value, str) and value.strip() else ""


def build_event(payload: dict) -> dict:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    args = tool_input.get("args")
    return {
        "ts": time.time(),
        "skill": _skill_name(tool_input),
        "args": args if isinstance(args, str) and args.strip() else None,
        "session_id": payload.get("session_id") or payload.get("sessionId"),
        "cwd": payload.get("cwd"),
    }


def log_path() -> str:
    return os.path.join(STATE_DIR, LOG_FILE_NAME)


def record_skill_usage(event: dict) -> None:
    """The single write path -- swap this for a real ingester later."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(log_path(), "a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> None:
    if not enabled():
        return
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    event = build_event(payload)
    if not event["skill"]:
        return
    try:
        record_skill_usage(event)
    except OSError:
        return


if __name__ == "__main__":
    main()
