"""Shared detection + checklist for bug-complaint leak hooks.

Deterministic only — no LLM. Fail-open callers catch any exception.
"""
from __future__ import annotations

import re
from typing import Iterable

# Phrases that mean "something is wrong in product," not ordinary implement work.
BUG_COMPLAINT_RES = [
    re.compile(r"\bwe have a bug\b", re.I),
    re.compile(r"\bthis is broken\b", re.I),
    re.compile(r"\bit'?s broken\b", re.I),
    re.compile(r"\brepro\b", re.I),
    re.compile(r"\breproduction\b", re.I),
    re.compile(r"doesn'?t keep\b", re.I),
    re.compile(r"does not keep\b", re.I),
    re.compile(r"\bfail[- ]clos", re.I),
    re.compile(r"draft not shown", re.I),
    re.compile(r"nothing was submitted", re.I),
    re.compile(r"\bbug report\b", re.I),
    re.compile(r"\binvestigate (this|the) bug\b", re.I),
]

# Ordinary implement asks that must NOT fire the checklist.
NON_BUG_RES = [
    re.compile(r"^add a comment to\b", re.I),
    re.compile(r"^please add a comment\b", re.I),
    re.compile(r"^rename\b", re.I),
]

QUOTE_RE = re.compile(
    r'"([^"\n]{8,120})"'
    r"|'([^'\n]{8,120})'"
    r"|`([^`\n]{8,120})`"
)


def extract_prompt_text(payload: dict) -> str:
    """Best-effort user prompt from Claude or Cursor hook stdin JSON."""
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return ""


def is_bug_complaint(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    for pattern in NON_BUG_RES:
        if pattern.search(text):
            return False
    return any(pattern.search(text) for pattern in BUG_COMPLAINT_RES)


def extract_quoted_symptoms(prompt: str, limit: int = 5) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in QUOTE_RE.finditer(prompt or ""):
        symptom = next((g for g in match.groups() if g), "").strip()
        if not symptom:
            continue
        key = symptom.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(symptom)
        if len(found) >= limit:
            break
    return found


def build_checklist(prompt: str) -> str:
    quotes = extract_quoted_symptoms(prompt)
    sample = quotes[0] if quotes else "<quoted symptom or error string>"
    quoted_list = ", ".join(f"`{q}`" for q in quotes) if quotes else "(none extracted — use the user-visible error string)"
    return "\n".join(
        [
            "Bug-complaint checklist (inject-only; fail-open; you still run the git):",
            f"1. Quoted product copy seen: {quoted_list}",
            f"2. How-we-got-here: `git log --all -S '{sample}'` and `git log --oneline --all --grep=<symptom>`.",
            "3. If workspace Grep of that copy is empty, run `git grep origin/master -e '<symptom>'` / `git log --all -S` before more local Grep.",
            "4. Class-search (CLAUDE.md): sibling jobs/hosts of the shared symbol; `gh pr list --search <file>` for unlanded fixes; fossil tests (`fails closed`, `toContainText` on the error string).",
            "5. Name every production host of the shared symbol before scoping the fix.",
            "Do not treat stack Non-goals that leave a shared policy alone as evidence the magic number is right.",
        ]
    )


def any_quote_in_pattern(pattern: str, quotes: Iterable[str]) -> bool:
    lowered = (pattern or "").lower()
    for quote in quotes:
        if quote.lower() in lowered or lowered in quote.lower():
            return True
    return False
