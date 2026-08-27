"""Detect first-person “my earlier check was wrong” admissions.

Assistant text only. Fail-open: parse/IO errors mean no hit. Once per
transcript. Skip if the user already asked /reflect.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Iterable

STATE_DIR = os.environ.get(
    "WRONG_CHECK_REFLECT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-wrong-check-reflect"),
)

ALREADY_REFLECT_RE = re.compile(r"(?i)\b/?reflect\b|\b/?automate-me\b|\bautomate me\b")

# Strip fenced code so tests / implementing this hook do not self-fire.
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# First-person retraction tied to a prior check/claim — not product blame,
# not bare "I was wrong", not hypotheticals.
ADMISSION_RES = [
    re.compile(
        r"(?i)\bmy\s+(earlier|previous|prior)\s+"
        r"(check|grep|read|assumption|claim|citation)\s+was\s+wrong\b"
    ),
    re.compile(
        r"(?i)\byou'?re\s+right,?\s+i\s+(misread|mis-read|misunderstood)\b"
    ),
    re.compile(
        r"(?i)\bi\s+incorrectly\s+assumed\b"
    ),
    re.compile(
        r"(?i)\bthe\s+file\s+i\s+(cited|named|pointed\s+to)\s+was\s+(a\s+)?duplicate\b"
    ),
    re.compile(
        r"(?i)\bgood\s+catch\b.{0,80}\bmy\s+(earlier|previous|prior)\s+"
        r"(check|grep|read|assumption|claim)\s+was\s+wrong\b",
        re.DOTALL,
    ),
    re.compile(
        r"(?i)\bi\s+(was\s+wrong|got\s+it\s+wrong)\s+(about|on)\s+"
        r"(the\s+)?(file|path|source|check|assumption)\b"
    ),
]

# Hypothetical / product-blame shapes that must stay silent even if a
# substring of a positive pattern appears nearby.
NEGATIVE_RES = [
    re.compile(r"(?i)\bif\s+my\s+(earlier|previous|prior)\s+check\s+was\s+wrong\b"),
    re.compile(r"(?i)\bthe\s+(test|ui|build|product|code)\s+was\s+wrong\b"),
]

FOLLOWUP = (
    "Wrong-check admission on this transcript ({match}). This is a FAILURE, "
    "not a preference ping: a claim went out before a real check. Finish the "
    "live correction first. Then read the reflect skill and spawn a subagent "
    "for steps 1-4 on this exact file: {path}. Present Accepted / Backlog / "
    "Route-to-automate-me / Rejected. Do not skip because the task also finished."
)

CODEX_ADVISORY = (
    "wrong-check-reflect: assistant admitted a prior check/claim was wrong "
    "({match}). Codex cannot force a rewrite — run /reflect on this session "
    "when convenient."
)


def strip_fences(text: str) -> str:
    return FENCE_RE.sub("", text or "")


def find_admission(text: str) -> str | None:
    """Return the matched phrase if text is a first-person wrong-check
    admission, else None."""
    cleaned = strip_fences(text)
    if not cleaned.strip():
        return None
    for pattern in NEGATIVE_RES:
        if pattern.search(cleaned):
            return None
    for pattern in ADMISSION_RES:
        match = pattern.search(cleaned)
        if match:
            return match.group(0)
    return None


def _state_file(transcript_path: str) -> str:
    key = transcript_path or "no-transcript"
    digest = hashlib.sha1(os.path.abspath(key).encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(transcript_path: str) -> bool:
    return os.path.isfile(_state_file(transcript_path or "no-transcript"))


def mark_prompted(transcript_path: str) -> None:
    path = _state_file(transcript_path or "no-transcript")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write((transcript_path or "") + "\n")
    except OSError:
        pass


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _message_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def user_already_asked_reflect(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_user_line(data):
                    continue
                text = _message_text(data)
                if not text or text.lstrip().startswith(
                    ("<command-", "<task-notification", "<system")
                ):
                    continue
                if ALREADY_REFLECT_RE.search(text):
                    return True
    except OSError:
        return False
    return False


def resolve_transcript(payload: dict) -> str:
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(
                    root, project, "agent-transcripts", conv, f"{conv}.jsonl"
                )
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    return ""


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def last_assistant_from_transcript(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_assistant_line(data):
                    continue
                text = _message_text(data)
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, transcript_path: str = "") -> str:
    for key in (
        "last_assistant_message",
        "last-assistant-message",
        "lastAssistantMessage",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(transcript_path)


def followup_for(match: str, path: str) -> str:
    return FOLLOWUP.format(match=match, path=path or "(no transcript path)")


def decide(payload: dict) -> str | None:
    """Return the follow-up instruction, or None to stay silent."""
    if not isinstance(payload, dict):
        return None
    if payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    text = last_assistant_text(payload, path)
    match = find_admission(text)
    if not match:
        return None
    if path and user_already_asked_reflect(path):
        return None
    key = path or text[:200]
    if already_prompted(key):
        return None
    mark_prompted(key)
    return followup_for(match, path)


def scan_assistant_texts(texts: Iterable[str]) -> list[str]:
    """Return matched admission phrases from a list of assistant texts."""
    hits = []
    for text in texts:
        match = find_admission(text or "")
        if match:
            hits.append(match)
    return hits
