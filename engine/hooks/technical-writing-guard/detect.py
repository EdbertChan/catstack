"""Stop a document rewrite that fails the technical-writing sentence checks.

Fires only when the user asked for a document. A chat reply stays silent.
A missing user prompt fails open. An unreadable reply is unchecked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_sdk"))
from finding import Finding  # noqa: E402

RULE_HIT = "technical-writing-guard.sentence"
RULE_UNCHECKED = "technical-writing-guard.unchecked"
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_RE = re.compile(r"`[^`\n]+`")
USER_KEYS = ("user_prompt", "prompt", "user_message")


def _grader():
    script_dir = Path(__file__).resolve().parents[3] / "product" / "skills" / "technical-writing" / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import grade_prose

    return grade_prose


def visible_prose(text: str) -> str:
    return INLINE_RE.sub(" ", FENCE_RE.sub(" ", text))


def user_text(event: dict) -> str | None:
    for key in USER_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def detect(event: dict) -> list[Finding]:
    if event.get("stop_hook_active"):
        return []
    asked = user_text(event)
    if asked is None:
        return []
    try:
        grader = _grader()
    except ImportError:
        return [
            Finding(
                rule_id=RULE_UNCHECKED,
                subject="technical writing grader",
                message="The document check could not load. Leave the reply unchecked.",
                evidence="grade_prose import failed",
            )
        ]
    if not grader.applies_to(asked):
        return []
    message = event.get("last_assistant_message")
    if not isinstance(message, str):
        return [
            Finding(
                rule_id=RULE_UNCHECKED,
                subject="document reply",
                message="The document reply could not be read. Leave it unchecked.",
                evidence="last_assistant_message missing",
            )
        ]
    hits = grader.sentence_findings(visible_prose(message))
    return [
        Finding(
            rule_id=RULE_HIT,
            subject="document sentence",
            message=hit,
            evidence=hit,
        )
        for hit in hits
    ]
