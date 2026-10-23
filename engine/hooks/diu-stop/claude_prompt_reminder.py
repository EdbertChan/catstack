#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: inject a short diu reminder as
additionalContext on the first human prompt of a session and again on the
first human prompt after each context compaction.

Complements claude_stop_check.py rather than replacing it. The Stop hook is
reactive -- it only catches a violation after the response is already
written, and it can't tell a legitimately long answer from a lazy one (pure
word count). This hook is proactive: it puts the rule in front of the model
right before it writes, at the one point in a very long, heavily-compacted
session where the original skill content is guaranteed to still be fresh --
the newest turn -- instead of relying on diu's instructions surviving
however many context compactions have happened by then.

Deliberately short and constant: no LLM, no attempt to detect whether the
last response actually needed it. Re-sending it on every single turn is
exactly the kind of bloat this skill tells the model to cut, so it stays
silent for a prompt that is not the human speaking (a task notification,
queued or system-injected input) and for a human prompt after the first one
of a session, until the transcript shows a new compaction boundary.

A prompt that relays a comment left on a document gets the comment cap
instead, on every such prompt: the user typed it by hand each time before.
"""
import os
import sys

from diu_limit import comment_rule_text, is_comment_prompt, rule_text

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from events import _prompt_text, is_human_prompt, once_per_session_or_compaction  # noqa: E402
from finding import Finding  # noqa: E402
from runtime import run_hook  # noqa: E402

RULE_REMINDER = "diu-stop.prompt-reminder"
RULE_COMMENT_REMINDER = "diu-stop.comment-prompt-reminder"

REMINDER = (
    "diu reminder: lead with the outcome, no preamble or closing "
    f"pleasantries, ELI5 {rule_text()}, unless this turn needs technical "
    "depth, number multi-step work, cap lists at 5, matter-of-fact tone on "
    "errors. Full rules: skills/diu/SKILL.md."
)

COMMENT_REMINDER = (
    "diu comment reply: this turn answers a comment on a document. Post the "
    f"reply in that comment thread, ELI5, {comment_rule_text()}. Lead with "
    "the answer or what changed, everyday words only. Full rules: "
    "skills/diu/SKILL.md Part 3."
)


def detect(event):
    if not is_human_prompt(event):
        return []
    subject = event.get("session_id") or ""
    if is_comment_prompt(_prompt_text(event)):
        return [Finding(rule_id=RULE_COMMENT_REMINDER, subject=subject, message=COMMENT_REMINDER, evidence=COMMENT_REMINDER)]
    if not once_per_session_or_compaction(RULE_REMINDER, event):
        return []
    return [Finding(rule_id=RULE_REMINDER, subject=subject, message=REMINDER, evidence=REMINDER)]


def main():
    run_hook("diu-stop", "claude", detect, "UserPromptSubmit")


if __name__ == "__main__":
    main()
