"""Score a document against the technical-writing checks.

A hit is a finding. An empty list is a pass. Nothing in the hook path calls
this yet.
"""

from __future__ import annotations

import re

SENTENCE_CHECKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("filler: say to", re.compile(r"\bin order to\b", re.I)),
    ("filler: delete the note", re.compile(r"it is important to (?:note|remember)", re.I)),
    ("filler: delete the note", re.compile(r"it's important to (?:note|remember)", re.I)),
    ("everyday word: use", re.compile(r"\butilize\b", re.I)),
    ("everyday word: help", re.compile(r"\bfacilitate\b", re.I)),
    ("procedure word: drop simply", re.compile(r"\bsimply\b", re.I)),
    ("em dash: start a new sentence", re.compile("—")),
    ("contrast frame: state the point", re.compile(r"\bnot just\b.{0,80}\bbut\b", re.I)),
    ("semicolon: use a period", re.compile(r";")),
    ("passive setup: name who acts", re.compile(r"\bis performed\b", re.I)),
    ("passive instruction: write the command", re.compile(r"\bshould (?:only )?be done\b", re.I)),
    ("metaphor noun: name the mechanism", re.compile(r"\bratchet\b", re.I)),
)

MODES = frozenset({"tutorial", "how-to", "reference", "explanation"})

TUTORIAL_LEAK = re.compile(r"you will learn", re.I)
STEP_LEAK = re.compile(r"(?m)^(First|Now),|^\d+\.\s|\bClick \b")
TASK_STEP = re.compile(
    r"(?m)^(Run|Click|Open|Add|Remove|Set|Write|Install|Create|First,|Now,)\b"
)
DOC_ASK = re.compile(
    r"\b(readme|docs?|rfc|commit message|pr (?:description|body)|pull request|"
    r"rewrite this|how-to|tutorial|reference page)\b",
    re.I,
)


def applies_to(user_text: str) -> bool:
    """True when the user asked for a document this skill owns."""
    return bool(DOC_ASK.search(user_text))


def sentence_findings(text: str) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for label, pattern in SENTENCE_CHECKS:
        if label in seen:
            continue
        if pattern.search(text):
            seen.add(label)
            hits.append(label)
    return hits


def mode_findings(text: str, mode: str) -> list[str]:
    if mode not in MODES:
        return [f"mode: {mode} is not tutorial, how-to, reference, or explanation"]
    hits: list[str] = []
    if mode != "tutorial" and TUTORIAL_LEAK.search(text):
        hits.append("mode: a lesson line is inside a non-tutorial")
    if mode == "reference" and STEP_LEAK.search(text):
        hits.append("mode: steps are inside a reference")
    if mode in ("tutorial", "how-to") and not TASK_STEP.search(text):
        hits.append("mode: a lesson or task has no step")
    return hits


def grade(text: str, mode: str) -> list[str]:
    return sentence_findings(text) + mode_findings(text, mode)
