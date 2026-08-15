#!/usr/bin/env python3
"""Claude Code Stop hook: deterministic (no LLM) diu word-count check.

Replaces the earlier `type: "prompt"` version. That one repeatedly ignored
the "output ONLY JSON" instruction and dumped its raw reasoning into the
transcript as "Stop hook feedback" -- including on turns it decided to
allow. This script can't judge nuance the way the LLM version tried to (a
response that's long because the user explicitly asked for a PR summary or
technical depth will still get flagged), but it can't malform its own
output either. Trade-off: fewer false "logs shown" surprises, more
false-positive blocks on legitimately long answers. Raise WORD_LIMIT if
that gets annoying.
"""
import json
import sys

WORD_LIMIT = 150


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    message = data.get("last_assistant_message") or ""
    word_count = len(message.split())
    if word_count <= WORD_LIMIT:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Apply diu: {word_count} words, over the {WORD_LIMIT}-word "
                "guideline. Rewrite shorter and in plain language, unless "
                "this turn genuinely asked for full technical detail or a "
                "specific long format."
            ),
        }
    }))


if __name__ == "__main__":
    main()
