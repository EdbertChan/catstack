"""Shared detection for split-scope inject hooks."""
from __future__ import annotations

import re

from state import load_state, save_state

REMINDER = (
    "split-scope: this prompt plans multi-slice work. Before writing the plan "
    "or PR stack, read the split-scope skill "
    "(product/skills/split-scope/SKILL.md, or the installed split-scope skill) "
    "and give each slice one review claim with a user-confirmed safety invariant."
)

TRIGGER_RES = (
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
    re.compile(r"\bplan\s+(?:a|the)\s+migration\b", re.I),
)
FENCE_RE = re.compile(r"```.*?```", re.S)
QUOTE_LINE_RE = re.compile(r"(?m)^\s*>.*$")
TASK_NOTIFICATION_RE = re.compile(r"<task-notification\b.*?</task-notification>", re.I | re.S)


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


def _live_prompt_text(prompt: str) -> str:
    text = prompt or ""
    text = TASK_NOTIFICATION_RE.sub(" ", text)
    text = FENCE_RE.sub(" ", text)
    text = QUOTE_LINE_RE.sub(" ", text)
    return text.strip()


def plans_multi_slice_work(prompt: str) -> bool:
    text = _live_prompt_text(prompt)
    if not text:
        return False
    return any(pattern.search(text) for pattern in TRIGGER_RES)


def remember_prompt(payload: dict) -> None:
    state = load_state(payload)
    state["cursor_prompt_pending"] = True
    save_state(payload, state)


def consume_prompt_pending(payload: dict) -> bool:
    state = load_state(payload)
    if not state.get("cursor_prompt_pending"):
        return False
    state["cursor_prompt_pending"] = False
    save_state(payload, state)
    return True
