"""handback-needs-attempt: judge unattempted hand-backs in the background."""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import uuid

HOOK_NAME = "handback-needs-attempt"
HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)

UNCHECKED_MESSAGE = "handback-needs-attempt: unchecked, letting this reply through: {reason}"
META_USER_PREFIXES = (
    "<local-command", "<task-notification", "<system", "Stop hook feedback")
ITEM_LIMIT = 400
EXCHANGE_LIMIT = 1500
REPLY_LIMIT = 2400


class TranscriptUnreadable(Exception):
    pass


def _content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def _is_tool_result_line(data: dict) -> bool:
    if data.get("toolUseResult") is not None:
        return True
    content = _content(data)
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _message_text(data: dict) -> str:
    content = _content(data)
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


def _is_person_line(data: dict) -> bool:
    if data.get("isMeta") or data.get("agentId") or data.get("isSidechain"):
        return False
    if _is_tool_result_line(data):
        return False
    message = data.get("message")
    if data.get("type") != "user" and not (isinstance(message, dict) and message.get("role") == "user"):
        return False
    return not _message_text(data).lstrip().startswith(META_USER_PREFIXES)


def read_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
    except (OSError, UnicodeDecodeError) as exc:
        raise TranscriptUnreadable(f"the transcript {path!r} could not be read ({exc!r})") from exc
    return rows


def turn_rows(rows: list[dict]) -> list[dict]:
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if _is_person_line(rows[index]):
            start = index + 1
            break
    return rows[start:]


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= ITEM_LIMIT else text[:ITEM_LIMIT] + "..."


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)


def tool_exchange(rows: list[dict]) -> list[str]:
    items: list[str] = []
    for data in turn_rows(rows):
        if data.get("isSidechain"):
            continue
        content = _content(data)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and _is_assistant_line(data):
                items.append(f"CALL {block.get('name')}: {_clip(block.get('input') or {})}")
            elif block.get("type") == "tool_result":
                label = "RESULT (error)" if block.get("is_error") else "RESULT"
                items.append(f"{label}: {_clip(_result_text(block))}")
    return items


def judge_text(reply: str, exchange: list[str]) -> str:
    calls = "\n".join(exchange) if exchange else "(no tool calls this turn)"
    return (
        "TOOL CALLS AND RESULTS THIS TURN:\n"
        + calls[-EXCHANGE_LIMIT:]
        + "\n\nASSISTANT REPLY:\n"
        + reply[-REPLY_LIMIT:]
    )


def reply_key(transcript_path: str, reply: str, exchange: list[str]) -> str:
    base = os.path.abspath(transcript_path) if transcript_path else "no-transcript"
    body = (reply or "") + "\n\x00\n" + "\n".join(exchange)
    return base + "\n" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _state_file(key: str) -> str:
    digest = hashlib.sha1((key or "no-transcript").encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    return os.path.isfile(_state_file(key))


def mark_prompted(key: str) -> None:
    path = _state_file(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write((key or "") + "\n")


def _supplied_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    return ""


def last_assistant_text(payload: dict, rows: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    last = ""
    for data in rows:
        if _is_assistant_line(data) and not data.get("isSidechain"):
            text = _message_text(data)
            if text.strip():
                last = text
    return last


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path:
        supplied = _supplied_transcript(payload)
        reason = (
            f"the transcript {supplied!r} could not be found" if supplied
            else "the payload names no readable transcript"
        )
        print(UNCHECKED_MESSAGE.format(reason=reason), file=sys.stderr)
        return None
    try:
        rows = read_rows(path)
    except TranscriptUnreadable as exc:
        print(UNCHECKED_MESSAGE.format(reason=str(exc)), file=sys.stderr)
        return None
    reply = last_assistant_text(payload, rows)
    if not reply.strip():
        return None
    exchange = tool_exchange(rows)
    key = reply_key(path, reply, exchange)
    if already_prompted(key):
        return None
    dictionary = _phrases().load(HOOK_NAME)
    job = _phrases().job(dictionary, path, judge_text(reply, exchange))
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK_NAME}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
