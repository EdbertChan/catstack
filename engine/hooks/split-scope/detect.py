"""Shared detection for split-scope prompt inject hooks."""
from __future__ import annotations

import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
from state import consume_pending, consume_pending_state, remember_pending

SKILL_PATH = "/".join(("product", "skills", "split-scope", "SKILL.md"))
REMINDER = (
    "split-scope: this prompt plans multi-slice work. Before writing the plan "
    f"or PR stack, read the split-scope skill ({SKILL_PATH}, or the installed "
    "split-scope skill) and give each slice one review claim with a "
    "user-confirmed safety invariant."
)
RULE_MULTI_SLICE_PROMPT = "split-scope.multi-slice-prompt"

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
    remember_pending(payload, extract_prompt_text(payload))


def consume_cursor_prompt(payload: dict) -> bool:
    return consume_pending(payload)


def detect(event: dict) -> list[Finding]:
    name = _event_name(event)
    prompt = extract_prompt_text(event)

    if name in {"beforeSubmitPrompt", "BeforeSubmitPrompt"}:
        if plans_multi_slice_work(prompt):
            remember_cursor_prompt(event)
        return []

    if name in {"postToolUse", "PostToolUse"}:
        pending = consume_pending_state(event)
        if pending is None:
            return []
        pending_prompt = str(pending.get("prompt") or "pending cursor prompt")
        return [_finding(pending_prompt)]

    if prompt and plans_multi_slice_work(prompt):
        return [_finding(prompt)]
    return []


def _event_name(event: dict) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _finding(prompt: str) -> Finding:
    return Finding(
        rule_id=RULE_MULTI_SLICE_PROMPT,
        subject=f"prompt:{_subject_hash(prompt)}",
        message=reminder_text(),
        evidence=prompt,
    )


def _subject_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
