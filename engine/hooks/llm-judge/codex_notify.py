#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys

import inbox


def main() -> None:
    if len(sys.argv) < 2:
        return
    raw = sys.argv[-1]
    chain = sys.argv[1:-1]

    if chain:
        try:
            subprocess.run(chain + [raw], timeout=5, check=False)
        except Exception as exc:
            print(f"llm-judge: chained notify failed: {exc}", file=sys.stderr)

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print(f"llm-judge: could not read the Codex notify payload: {exc}", file=sys.stderr)
        return
    if not isinstance(payload, dict) or payload.get("type") != "agent-turn-complete":
        return

    transcript = inbox.resolve_transcript(payload)
    if not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness="Codex notify"), file=sys.stderr)
        return
    try:
        found = inbox.messages(transcript)
    except Exception as exc:
        print(f"llm-judge: could not drain verdicts for {transcript}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    for message in found:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
