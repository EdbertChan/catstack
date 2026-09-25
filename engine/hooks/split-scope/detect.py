"""Shared detection for split-scope prompt inject hooks."""
from __future__ import annotations

import re
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
from state import consume_pending, consume_pending_data, remember_pending

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
RULE_MULTI_SLICE_WORK = "split-scope.multi-slice-work"


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


def detect(event: dict[str, object]) -> list[Finding]:
    prompt = extract_prompt_text(event)
    if not plans_multi_slice_work(prompt):
        return []
    return [_finding_for_prompt(prompt)]


def detect_cursor_before_submit(event: dict[str, object]) -> list[Finding]:
    prompt = extract_prompt_text(event)
    if plans_multi_slice_work(prompt):
        finding = _finding_for_prompt(prompt)
        remember_pending(
            event,
            {
                "rule_id": finding.rule_id,
                "subject": finding.subject,
                "message": finding.message,
                "evidence": finding.evidence,
            },
        )
    return []


def detect_cursor_post_tool_use(event: dict[str, object]) -> list[Finding]:
    data = consume_pending_data(event)
    if data is None:
        return []
    return [
        Finding(
            rule_id=data.get("rule_id") or RULE_MULTI_SLICE_WORK,
            subject=data.get("subject") or _subject_for_prompt("pending-cursor-prompt"),
            message=data.get("message") or reminder_text(),
            evidence=data.get("evidence") or "pending cursor prompt",
        )
    ]


def remember_cursor_prompt(payload: dict) -> None:
    prompt = extract_prompt_text(payload)
    finding = _finding_for_prompt(prompt) if plans_multi_slice_work(prompt) else None
    if finding is None:
        return
    remember_pending(
        payload,
        {
            "rule_id": finding.rule_id,
            "subject": finding.subject,
            "message": finding.message,
            "evidence": finding.evidence,
        },
    )


def consume_cursor_prompt(payload: dict) -> bool:
    return consume_pending(payload)


def _finding_for_prompt(prompt: str) -> Finding:
    return Finding(
        rule_id=RULE_MULTI_SLICE_WORK,
        subject=_subject_for_prompt(prompt),
        message=reminder_text(),
        evidence=_trigger_evidence(prompt),
    )


def _subject_for_prompt(prompt: str) -> str:
    digest = hashlib.sha256((prompt or "").strip().encode("utf-8")).hexdigest()
    return f"prompt:{digest}"


def _trigger_evidence(prompt: str) -> str:
    for pattern in TRIGGERS:
        match = pattern.search(prompt or "")
        if match:
            return match.group(0)
    return "multi-slice prompt"
