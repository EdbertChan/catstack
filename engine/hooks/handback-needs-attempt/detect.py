from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HERE)
JUDGE_PATH = os.path.join(HOOKS_DIR, "llm-judge", "judge.py")
PHRASES_PATH = os.path.join(HOOKS_DIR, "llm-judge", "phrases.py")
UNCHECKED = "unchecked"


def _is_assistant(data: dict) -> bool:
    message = data.get("message")
    return data.get("type") == "assistant" or (
        isinstance(message, dict) and message.get("role") == "assistant"
    )


def _is_human(data: dict) -> bool:
    message = data.get("message")
    if data.get("type") != "user" and not (
        isinstance(message, dict) and message.get("role") == "user"
    ):
        return False
    if data.get("isMeta") or data.get("isSidechain") or data.get("toolUseResult") is not None:
        return False
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    ):
        return False
    return True


def _text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _transcript(path: str) -> list[dict] | None:
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError as exc:
        print(f"handback-needs-attempt: {UNCHECKED}: cannot read transcript: {exc}", file=sys.stderr)
        return None
    return rows


def resolve_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and os.path.isfile(value):
            return value
    return ""


def _current_exchange(rows: list[dict]) -> list[dict]:
    start = 0
    for index, row in enumerate(rows):
        if _is_human(row):
            start = index
    return rows[start:]


def _last_reply(payload: dict, rows: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for row in reversed(rows):
        if _is_assistant(row) and _text(row).strip():
            return _text(row)
    return ""


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
    spec = importlib.util.spec_from_file_location("handback_llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(PHRASES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path:
        supplied = next(
            (payload.get(key) for key in ("agent_transcript_path", "transcript_path", "transcriptPath")
             if isinstance(payload.get(key), str) and payload.get(key)),
            None,
        )
        if supplied:
            print(f"handback-needs-attempt: {UNCHECKED}: cannot read transcript: {supplied}", file=sys.stderr)
        return None
    rows = _transcript(path)
    if rows is None:
        return None
    reply = _last_reply(payload, rows)
    if not reply.strip():
        return None
    dictionary = _phrases().load("handback-needs-attempt")
    job = _phrases().job(dictionary, path, reply)
    job["id"] = uuid.uuid4().hex
    job["exchange"] = _current_exchange(rows)
    job["tool_calls_and_results"] = _current_exchange(rows)
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"handback-needs-attempt: {UNCHECKED}: {type(exc).__name__}: {exc}", file=sys.stderr)
