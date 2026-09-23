#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: inject a short diu reminder as
additionalContext before generation starts on every turn.

Complements claude_stop_check.py rather than replacing it. The Stop hook is
reactive -- it only catches a violation after the response is already
written, and it can't tell a legitimately long answer from a lazy one (pure
word count). This hook is proactive: it puts the rule in front of the model
right before it writes, at the one point in a very long, heavily-compacted
session where the original skill content is guaranteed to still be fresh --
the newest turn -- instead of relying on diu's instructions surviving
however many context compactions have happened by then.

Deliberately short and constant: no LLM, no per-turn conditional logic, no
attempt to detect whether the last response actually needed it. A longer
reminder repeated every turn is exactly the kind of thing this skill tells
the model to cut.
"""
import os
import sys

from diu_limit import rule_text

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from events import should_inject_reminder  # noqa: E402
from finding import Finding  # noqa: E402
from runtime import run_hook  # noqa: E402

RULE_REMINDER = "diu-stop.prompt-reminder"

REMINDER = (
    "diu reminder: lead with the outcome, no preamble or closing "
    f"pleasantries, ELI5 {rule_text()}, unless this turn needs technical "
    "depth, number multi-step work, cap lists at 5, matter-of-fact tone on "
    "errors. Full rules: skills/diu/SKILL.md."
)


def detect(event):
    if not should_inject_reminder("diu-stop", event):
        return []
    subject = event.get("session_id") or ""
    return [Finding(rule_id=RULE_REMINDER, subject=subject, message=REMINDER, evidence=REMINDER)]


def main():
    run_hook("diu-stop", "claude", detect, "UserPromptSubmit")


if __name__ == "__main__":
    main()
