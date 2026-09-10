#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: inject a short diu reminder as
additionalContext before generation starts on every turn.

Deliberately short and constant: no LLM, no per-turn conditional logic, no
attempt to detect whether the last response actually needed it. A longer
reminder repeated every turn is exactly the kind of thing this skill tells
the model to cut.
"""
import json
import sys

from word_rule import describe

REMINDER = (
    "diu reminder: lead with the outcome, no preamble or closing "
    f"pleasantries, ELI5 {describe()} unless this turn needs technical "
    "depth, number multi-step work, cap lists at 5, matter-of-fact tone on "
    "errors. Full rules: skills/diu/SKILL.md."
)


def main():
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": REMINDER,
        }
    }))


if __name__ == "__main__":
    main()
