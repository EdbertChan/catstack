#!/usr/bin/env python3
"""Codex `notify` hook: advisory-only diu-brevity reminder.

Codex's notify hook fires once, after the turn is already over, with no way
to block or make Codex redo anything -- unlike Claude Code's Stop hook or
Cursor's stop hook. This can only print a heads-up to the terminal; a human
(or the next turn) has to act on it.

Chains to another notify command if one was already configured, so
installing this doesn't silently drop it. No machine-specific path lives in
this file: Codex always appends its JSON payload as the last argv element,
so everything between the script path and that last element is treated as
the chain command, e.g.:

    notify = ["python3", "/path/to/codex_notify.py", "/path/to/old-notify-binary", "some-arg"]

becomes `old-notify-binary some-arg <json-payload>` when this fires.
"""
import json
import subprocess
import sys

WORD_LIMIT = 150


def main():
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]

    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"diu-stop: chained notify failed: {exc}", file=sys.stderr)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    if payload.get("type") != "agent-turn-complete":
        return

    message = payload.get("last-assistant-message") or ""
    word_count = len(message.split())
    if word_count > WORD_LIMIT:
        print(
            f"diu-stop: last response was {word_count} words (over the "
            f"{WORD_LIMIT}-word diu guideline). Codex can't be forced to redo "
            "it -- check by hand whether it should have been ELI5.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
