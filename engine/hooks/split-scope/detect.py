"""Shared detection for split-scope prompt inject hooks."""
from __future__ import annotations

import re

from state import consume_pending, remember_pending

SKILL_PATH = "/".join(("product", "skills", "split-scope", "SKILL.md"))
REMINDER = (
    "split-scope: this prompt plans multi-slice work. Before writing the plan "
    f"or PR stack, read the split-scope skill ({SKILL_PATH}, or the installed "
    "split-scope skill) and give each slice one review claim with a "
    "user-confirmed safety invariant."
)

TRIGGERS = (
    re.compile(r"\bpr\s+stack\b", re.I),
    re.compile(r"\bstack\s+of\s+prs\b", re.I),
    re.compile(r"\bstacked\s+prs\b", re.I),
    re.compile(r"\bmultiple\s+prs\b", re.I),
    re.compile(r"\bseveral\s+prs\b", re.I),
    re.compile(r"\bmulti[-\s]?pr\b", re.I),
    re.compile(r"\bsplit\s+this\s+into\b", re.I),
    re.compile(r"\bbreak\s+this\s+into\s+prs\b", re.I),
    re.compile(r"\binto\s+slices\b", re.I),
    re.compile(r"\bmigration\s+plan\b", re.I),
    re.compile(r"\bplan\s+a\s+migration\b", re.I),
    re.compile(r"\bplan\s+the\s+migration\b", re.I),
)


def reminder_text() -> str:
    return REMINDER


def extract_prompt_text(payload: dict) -> str:
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


def plans_multi_slice_work(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in TRIGGERS)


def remember_cursor_prompt(payload: dict) -> None:
    remember_pending(payload)


def consume_cursor_prompt(payload: dict) -> bool:
    return consume_pending(payload)
