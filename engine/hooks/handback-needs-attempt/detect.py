from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_PATH = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge", "judge.py")
PHRASES_PATH = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge", "phrases.py")
STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)
STATE_TTL_SECONDS = 2 * 60 * 60


def _state_file(key: str) -> str:
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    try:
        with open(_state_file(key), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return False
    prompted_at = state.get("prompted_at") if isinstance(state, dict) else None
    return (
        state.get("key") == key
        and isinstance(prompted_at, (int, float))
        and not isinstance(prompted_at, bool)
        and 0 <= time.time() - prompted_at < STATE_TTL_SECONDS
    )


def mark_prompted(key: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_file(key), "w", encoding="utf-8") as handle:
        json.dump({"key": key, "prompted_at": time.time()}, handle)


def _message_content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _text(data: dict) -> str:
    content = _message_content(data)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif block.get("type") in {"tool_use", "tool_result"}:
                parts.append(json.dumps(block, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def _human_user(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    content = _message_content(data)
    if isinstance(content, str):
        return bool(content.strip()) and not content.lstrip().startswith(("<command-", "<task-notification", "<system"))
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "text" and (block.get("text") or "").strip()
        for block in content
    )


def _payload_transcript(payload: dict) -> tuple[str, bool]:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str) and os.path.isfile(value):
            return value, True
        return "", True
    return "", False


def exchange_from_transcript(path: str) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    start = 0
    for index, data in enumerate(lines):
        if isinstance(data, dict) and _human_user(data):
            start = index
    return "\n".join(_text(data) for data in lines[start:] if isinstance(data, dict))


def last_assistant_text(payload: dict, path: str) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    exchange = exchange_from_transcript(path)
    return exchange or ""


def decide(_payload: dict) -> None:
    return None


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(LLM_JUDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(PHRASES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path, path_was_supplied = _payload_transcript(payload)
    if path_was_supplied and not path:
        return None
    if not path:
        return None
    exchange = exchange_from_transcript(path)
    if exchange is None:
        return None
    reply = last_assistant_text(payload, path)
    if not reply.strip() or already_prompted(path):
        return None
    text = "\n\nLATEST REPLY:\n" + reply + "\n\nTURN EXCHANGE:\n" + exchange
    dictionary = _phrases().load("handback-needs-attempt")
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        mark_prompted(path)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error handback-needs-attempt: {type(exc).__name__}: {exc}", file=sys.stderr)
