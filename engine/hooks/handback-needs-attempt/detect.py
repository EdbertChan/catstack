from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
JUDGE_PATH = os.path.join(JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(JUDGE_DIR, "phrases.py")
STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)
FOLLOWUP = "handback-needs-attempt: attempt the command or step before handing it back; if only the user can do it, name the permission, consent, password, or hardware boundary."


def _message(data: dict) -> dict:
    value = data.get("message")
    return value if isinstance(value, dict) else data


def _content(data: dict) -> object:
    return _message(data).get("content")


def _role(data: dict) -> str:
    message = _message(data)
    return str(message.get("role") or data.get("type") or "")


def _is_tool_result(data: dict) -> bool:
    content = _content(data)
    return data.get("toolUseResult") is not None or (
        isinstance(content, list)
        and any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
    )


def _is_harness_row(data: dict) -> bool:
    return bool(data.get("isMeta") or data.get("isSidechain") or data.get("agentId") or _is_tool_result(data))


def _block_text(block: dict) -> str:
    kind = block.get("type")
    if kind == "text":
        return str(block.get("text") or "")
    if kind == "tool_use":
        return f"tool call {block.get('name') or ''}: {json.dumps(block.get('input') or {}, ensure_ascii=False)}"
    if kind == "tool_result":
        return f"tool result: {block.get('content') or ''}"
    return ""


def _text(data: dict) -> str:
    content = _content(data)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_block_text(block) for block in content if isinstance(block, dict)).strip()
    return ""


def _rows(path: str) -> list[dict] | None:
    result = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    result.append(data)
    except OSError as exc:
        print(f"catstack-hook-error handback-needs-attempt: cannot read {path}: {exc}", file=sys.stderr)
        return None
    return result


def resolve_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        path = payload.get(key)
        if isinstance(path, str) and os.path.isfile(path):
            return path
    return ""


def last_assistant(payload: dict, rows: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for data in reversed(rows):
        if _role(data) == "assistant" and not _is_harness_row(data):
            value = _text(data)
            if value.strip():
                return value
    return ""


def exchange(path: str, reply: str) -> str:
    rows = (_rows(path) if path else []) or []
    start = 0
    for index, data in enumerate(rows):
        if _role(data) == "user" and not _is_harness_row(data):
            start = index
    parts = []
    for data in rows[start:]:
        text = _text(data)
        if text:
            parts.append(f"{_role(data)}: {text}")
    if not parts or parts[-1] != f"assistant: {reply}":
        parts.append(f"assistant: {reply}")
    return "\n\n--- next turn record ---\n\n".join(parts)[-12000:]


def _state_file(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def _already_prompted(key: str) -> bool:
    return os.path.isfile(_state_file(key))


def _mark_prompted(key: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_file(key), "w", encoding="utf-8") as handle:
        handle.write(key)


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("handback_llm_judge", JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(JUDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("handback_llm_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(PHRASES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    rows = _rows(path) if path else []
    if rows is None:
        return None
    reply = last_assistant(payload, rows)
    if not reply.strip():
        return None
    key = f"{os.path.abspath(path) if path else 'no-transcript'}\n{hashlib.sha256(reply.encode()).hexdigest()}"
    if _already_prompted(key):
        return None
    dictionary = _phrases().load("handback-needs-attempt")
    prompt = _phrases().prompt(dictionary, exchange(path, reply))
    job = _phrases().job(dictionary, path, reply)
    job["prompt"] = prompt
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        _mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error handback-needs-attempt: {type(exc).__name__}: {exc}", file=sys.stderr)
