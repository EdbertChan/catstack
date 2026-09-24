#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

import inbox

HARNESS = "Claude PostToolUse"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"llm-judge: {HARNESS} could not read payload: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    transcript = inbox.resolve_transcript(payload) if isinstance(payload, dict) else ""
    if not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness=HARNESS), file=sys.stderr)
        return
    try:
        found, unchecked = inbox.report(transcript)
    except Exception as exc:
        print(f"llm-judge: {HARNESS} could not drain verdicts for {transcript}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    if not found:
        return
    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n\n".join(found)}}
    notice = inbox.user_notice(unchecked)
    if notice:
        output["systemMessage"] = notice
    print(json.dumps(output))


if __name__ == "__main__":
    main()
