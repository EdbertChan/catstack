#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

import inbox


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"llm-judge: could not read the Cursor stop payload: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(json.dumps({}))
        return
    transcript = inbox.resolve_transcript(payload) if isinstance(payload, dict) else ""
    if not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness="Cursor stop"), file=sys.stderr)
        print(json.dumps({}))
        return
    try:
        found = inbox.messages(transcript)
    except Exception as exc:
        print(f"llm-judge: could not drain verdicts for {transcript}: {type(exc).__name__}: {exc}", file=sys.stderr)
        found = []
    print(json.dumps({"followup_message": "\n\n".join(found)} if found else {}))


if __name__ == "__main__":
    main()
