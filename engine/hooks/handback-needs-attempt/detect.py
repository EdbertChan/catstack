from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from transcripts import codex_rollout

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_PATH = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge", "judge.py")
PHRASES_PATH = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge", "phrases.py")
STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)
CHECKER = "handback-needs-attempt"
STATE_TTL_SECONDS = 2 * 60 * 60


def reply_key(transcript_path: str, text: str) -> str:
    path = os.path.abspath(transcript_path) if transcript_path else "no-transcript"
    return path + "\n" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _state_file(key: str) -> str:
    digest = hashlib.sha1((key or "no-transcript").encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    try:
        return time.time() - os.path.getmtime(_state_file(key)) < STATE_TTL_SECONDS
    except OSError:
        return False


def mark_prompted(key: str) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_file(key), "w", encoding="utf-8") as handle:
        handle.write((key or "") + "\n")


def _message(data: dict) -> dict:
    value = data.get("message")
    return value if isinstance(value, dict) else data


def _content(data: dict) -> object:
    return _message(data).get("content")


def _text(data: dict) -> str:
    content = _content(data)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _is_assistant(data: dict) -> bool:
    return data.get("type") == "assistant" or _message(data).get("role") == "assistant"


def _is_user(data: dict) -> bool:
    return data.get("type") == "user" or _message(data).get("role") == "user"


def _is_tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None:
        return True
    content = _content(data)
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_harness_row(data: dict) -> bool:
    return bool(data.get("isMeta") or data.get("isSidechain") or data.get("agentId"))


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    for key in ("transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and os.path.isfile(value):
            return value
    return codex_rollout(payload)


def last_assistant_from_transcript(path: str) -> str:
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and _is_assistant(data) and _text(data).strip():
                    last = _text(data)
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, transcript_path: str = "") -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(transcript_path) if transcript_path else ""


def _read_rows(path: str) -> list[dict] | None:
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
    except OSError as exc:
        print(f"catstack-hook-error {CHECKER}: cannot read transcript: {exc}", file=sys.stderr)
        return None
    return rows


def _exchange(rows: list[dict], reply: str) -> str:
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if _is_user(row) and not _is_harness_row(row) and not _is_tool_result(row):
            start = index
            break
    records = []
    for row in rows[start:]:
        if _is_harness_row(row) or not (_is_user(row) or _is_assistant(row)):
            continue
        records.append(row)
    records.append({"type": "assistant", "message": {"role": "assistant", "content": reply}})
    return json.dumps(records, ensure_ascii=False, sort_keys=True)


def exchange_for_reply(path: str, reply: str) -> str | None:
    rows = _read_rows(path)
    return None if rows is None else _exchange(rows, reply)


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("handback_llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("handback_llm_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict, harness: str = "unknown") -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    transcript = resolve_transcript(payload)
    reply = last_assistant_text(payload, transcript)
    if not transcript or not reply.strip():
        return None
    key = reply_key(transcript, reply)
    if already_prompted(key):
        return None
    exchange = exchange_for_reply(transcript, reply)
    if exchange is None:
        return None
    dictionary = _phrases().load(CHECKER)
    job = _phrases().job(dictionary, transcript, exchange)
    job["id"] = uuid.uuid4().hex
    job["harness"] = harness
    job_id = _judge().enqueue(job)
    if job_id is None:
        return None
    mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict, harness: str = "unknown") -> None:
    try:
        enqueue_judge(payload, harness)
    except Exception as exc:
        print(f"catstack-hook-error {CHECKER}: {type(exc).__name__}: {exc}", file=sys.stderr)
