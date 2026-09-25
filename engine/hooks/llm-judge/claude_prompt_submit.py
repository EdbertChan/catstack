#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

import inbox


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"llm-judge: could not read the UserPromptSubmit payload: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    transcript = payload.get("transcript_path") if isinstance(payload, dict) else None
    if not isinstance(transcript, str) or not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness="Claude UserPromptSubmit"), file=sys.stderr)
        return
    try:
        found, unchecked = inbox.report(transcript)
    except Exception as exc:
        print(f"llm-judge: could not drain verdicts for {transcript}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    if not found:
        return
    output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n\n".join(found)}}
    notice = inbox.user_notice(unchecked)
    if notice:
        output["systemMessage"] = notice
    print(json.dumps(output))


if __name__ == "__main__":
    main()
