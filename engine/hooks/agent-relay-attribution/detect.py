"""agent-relay-attribution: a fact relayed from a subagent is the agent's
claim, not the reply's own observation.

A relay arrives two ways: a task-notification block (a subagent's result)
and a teammate message (`<teammate-message teammate_id="..." ...>`), which
is how a message sent between agents lands in the recipient's transcript.
Both count. When one arrived within the last three turns and the reply
asserts facts (passed, merged, fixed, landed, green, because, numbers)
without saying they come from the agent ("per the agent's report", "the
agent reported") and without this turn's own command output showing any of
those facts, the reply is presenting a relay as a first-hand observation.

A verification tool having run is not enough: the tool result has to
contain one of the facts the reply asserts, so a command that checked
something unrelated stops counting as evidence for the relayed claim.

Advisory only: the hook returns a note, never blocks. Judgment (was the
claim really relayed, is every fact covered) stays with the model; this
file matches shapes and fails open.
"""
from __future__ import annotations

import json
import re

STATUS_RE = re.compile(
    r"\b(?:passed|passing|merged|fixed|landed|green|succeeded|success)\b",
    re.IGNORECASE,
)
FACT_RE = re.compile(STATUS_RE.pattern + r"|\bbecause\b|\b\d+\b", re.IGNORECASE)
EVIDENCE_NUMBER_RE = re.compile(r"\b\d{2,}\b")
ATTRIBUTION_RE = re.compile(
    r"\bper (?:the |its |their )?(?:sub)?agent'?s?(?: report| output| summary)?\b|"
    r"\bthe (?:sub)?agent (?:reported|reports|says|said|found|wrote|pasted|flagged)\b|"
    r"\baccording to the (?:sub)?agent\b|"
    r"\b(?:pasted|relayed|quoted) (?:by|from) the (?:sub)?agent\b|"
    r"\b(?:sub)?agent'?s? (?:report|output|summary|paste)\b|"
    r"\bits report\b|\brelayed\b|\bnot (?:re-?)?verified by me\b",
    re.IGNORECASE,
)
TEAMMATE_ENVELOPE_RE = re.compile(
    r"<teammate-message\b([^>]*)>(.*?)(?:</teammate-message>|\Z)", re.DOTALL
)
TEAMMATE_ID_RE = re.compile(r'teammate_id="([^"]*)"')
VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "Monitor", "WebFetch"}
RECENT_TURNS = 3

MESSAGE = (
    "attribute relayed claims or re-verify (agent-relay-attribution): a subagent result "
    "arrived within the last {n} turns and this reply states {facts} as fact with no "
    "'per the agent's report' and no command output this turn showing any of them."
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
    """Indexes of user lines that start a response: human text, a
    task-notification or a teammate message, not a tool_result."""
    out: list[int] = []
    for i, data in enumerate(lines):
        if data.get("type") != "user" or _is_tool_result_line(data):
            continue
        if _text_content(data).strip():
            out.append(i)
    return out


def teammate_claim(text: str) -> bool:
    """True when a teammate message carries an agent's own words rather than
    only harness control payloads (`teammate_id="system"`, JSON envelopes
    such as teammate_terminated or shutdown_approved)."""
    for attrs, body in TEAMMATE_ENVELOPE_RE.findall(text or ""):
        speaker = TEAMMATE_ID_RE.search(attrs)
        if speaker and speaker.group(1) == "system":
            continue
        stripped = (body or "").strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return True
        if not isinstance(payload, dict) or "type" not in payload:
            return True
    return False


def relay_arrived(lines: list[dict], turns: int = RECENT_TURNS) -> bool:
    for i in turn_boundaries(lines)[-turns:]:
        text = _text_content(lines[i])
        if text.lstrip().startswith("<task-notification"):
            return True
        if "<teammate-message" in text and teammate_claim(text):
            return True
    return False


def evidence_tokens(text: str) -> set[str]:
    """The parts of a claim a command's output can corroborate: status words
    and multi-digit numbers. A bare 'because' and single digits are dropped --
    too common in unrelated output to prove anything about this claim."""
    tokens = {m.group(0).lower() for m in STATUS_RE.finditer(text or "")}
    tokens.update(EVIDENCE_NUMBER_RE.findall(text or ""))
    return tokens


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def verification_output_this_turn(lines: list[dict]) -> str:
    """Text printed this turn by a verification tool, keyed by tool_use id so
    a result is only counted for the tool that produced it."""
    bounds = turn_boundaries(lines)
    start = bounds[-1] if bounds else 0
    verify_ids: set[str] = set()
    chunks: list[str] = []
    for data in lines[start:]:
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if (
                data.get("type") == "assistant"
                and block.get("type") == "tool_use"
                and block.get("name") in VERIFY_TOOLS
            ):
                verify_ids.add(block.get("id"))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in verify_ids:
                chunks.append(_tool_result_text(block))
    return "\n".join(chunks)


def claim_shown_this_turn(message: str, lines: list[dict]) -> bool:
    claimed = evidence_tokens(message)
    if not claimed:
        return False
    return bool(claimed & evidence_tokens(verification_output_this_turn(lines)))


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
    if not relay_arrived(lines):
        return None
    if claim_shown_this_turn(message, lines):
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
