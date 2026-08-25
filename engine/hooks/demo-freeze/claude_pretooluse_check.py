#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): demo-surface freeze.

While the user is mid-test on a live demo, the demo surface must not change
under them. The agent (or user) declares a freeze by writing the frozen paths
— one absolute path, directory (trailing slash), or glob per line — to
/tmp/.demo-freeze when a live-demo window opens, and deleting the file when
it closes (see CLAUDE.md live-demo rules). While the marker exists, edits to
matching paths are blocked (exit 2).

Motivated by a /reflect on a 2026-08-17 session: an unrequested layout edit
to the demo page during the user's test window corrupted it mid-demo
("WHAT THE FUCK IS THIS FULL TV LAYOUT").

Safety valves: the marker auto-expires after 2 hours (a forgotten freeze must
not haunt tomorrow's session), and any parse/read error fails open.
"""
import fnmatch
import json
import os
import sys
import time

MARKER = os.environ.get("DEMO_FREEZE_FILE", "/tmp/.demo-freeze")
MAX_AGE_SECS = 2 * 3600


def frozen_patterns():
    try:
        stat = os.stat(MARKER)
    except OSError:
        return []
    if time.time() - stat.st_mtime > MAX_AGE_SECS:
        return []  # stale freeze: auto-expire rather than brick future sessions
    try:
        with open(MARKER) as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def matches(target, pattern):
    target_abs = os.path.abspath(target)
    if pattern.endswith("/"):
        return target_abs.startswith(os.path.abspath(pattern) + os.sep)
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(target_abs, pattern)
    return target_abs == os.path.abspath(pattern)


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    tool_input = data.get("tool_input") or {}
    target = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
    )
    if not target:
        return
    for pattern in frozen_patterns():
        if matches(target, pattern):
            sys.stderr.write(
                f"Demo surface frozen: {target} matches {pattern!r} in {MARKER}. "
                "The user is mid-test — don't change what they're looking at unless "
                "they asked or the test is failing. Remove the marker file to "
                "unfreeze once the live window ends.\n"
            )
            sys.exit(2)


if __name__ == "__main__":
    main()
