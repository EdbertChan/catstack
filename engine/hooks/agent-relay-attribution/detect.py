"""agent-relay-attribution: a fact relayed from a subagent is the agent's
claim, not the reply's own observation.

When a task-notification (a subagent's result) arrived within the last
three turns and the reply asserts facts (passed, merged, fixed, landed,
green, because, numbers) without saying they come from the agent ("per the
agent's report", "the agent reported") and without a same-turn verification
command, the reply is presenting a relay as a first-hand observation.
Advisory only: the hook returns a note, never blocks. Judgment (was the
claim really relayed) stays with the model; this file matches shapes and
fails open.
"""
from __future__ import annotations

import json
import re

FACT_RE = re.compile(
    r"\b(?:passed|passing|merged|fixed|landed|green|because|succeeded|success)\b|\b\d+\b",
    re.IGNORECASE,
)
ATTRIBUTION_RE = re.compile(
    r"\bper (?:the |its |their )?(?:sub)?agent'?s?(?: report| output| summary)?\b|"
    r"\bthe (?:sub)?agent (?:reported|reports|says|said|found|wrote|pasted|flagged)\b|"
    r"\baccording to the (?:sub)?agent\b|"
    r"\b(?:pasted|relayed|quoted) (?:by|from) the (?:sub)?agent\b|"
    r"\b(?:sub)?agent'?s? (?:report|output|summary|paste)\b|"
    r"\bits report\b|\brelayed\b|\bnot (?:re-?)?verified by me\b",
    re.IGNORECASE,
)
VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "Monitor", "WebFetch"}
RECENT_TURNS = 3

MESSAGE = (
    "attribute relayed claims or re-verify (agent-relay-attribution): a subagent result "
    "arrived within the last {n} turns and this reply states {facts} as fact with no "
    "'per the agent's report' and no verification command this turn."
)


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_tool_result_line(data: dict) -> bool:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def parse_lines(raw_lines) -> list[dict]:
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def turn_boundaries(lines: list[dict]) -> list[int]:
    """Indexes of user lines that start a response: human text or a
    task-notification, not a tool_result."""
    out: list[int] = []
    for i, data in enumerate(lines):
        if data.get("type") != "user" or _is_tool_result_line(data):
            continue
        if _text_content(data).strip():
            out.append(i)
    return out


def recent_notification(lines: list[dict], turns: int = RECENT_TURNS) -> bool:
    for i in turn_boundaries(lines)[-turns:]:
        if _text_content(lines[i]).lstrip().startswith("<task-notification"):
            return True
    return False


def verified_this_turn(lines: list[dict]) -> bool:
    bounds = turn_boundaries(lines)
    start = bounds[-1] if bounds else 0
    for data in lines[start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in VERIFY_TOOLS:
                return True
    return False


def facts_in(text: str) -> list[str]:
    seen: list[str] = []
    for match in FACT_RE.finditer(text or ""):
        word = match.group(0).lower()
        if word not in seen:
            seen.append(word)
    return seen


def decide_from_lines(message: str, lines: list[dict]) -> str | None:
    facts = facts_in(message)
    if not facts:
        return None
    if ATTRIBUTION_RE.search(message):
        return None
    if not recent_notification(lines):
        return None
    if verified_this_turn(lines):
        return None
    shown = ", ".join(f'"{f}"' for f in facts[:4])
    return MESSAGE.format(n=RECENT_TURNS, facts=shown)


def decide(payload: dict) -> str | None:
    """Return an advisory note for the Stop event, or None."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not facts_in(message) or ATTRIBUTION_RE.search(message):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not transcript_path:
        return None
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = parse_lines(handle)
    except OSError:
        return None
    return decide_from_lines(message, lines)
