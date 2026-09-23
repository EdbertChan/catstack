from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import uuid

HOOK_NAME = "handback-needs-attempt"
HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_PATH = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge", "judge.py")
PHRASES_PATH = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge", "phrases.py")
UNCHECKED = "handback-needs-attempt: transcript unavailable; hand-back check is unchecked and will not flag this reply"


def _is_assistant(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def _is_tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None:
        return True
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _is_user(data: dict) -> bool:
    if data.get("isMeta") or data.get("isSidechain") or _is_tool_result(data):
        return False
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def resolve_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and os.path.isfile(value):
            return value
    return ""


def _exchange(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        return None
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if _is_user(rows[index]):
            start = index
            break
    selected = rows[start:]
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in selected)


def last_assistant_text(payload: dict, transcript: str) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    last = ""
    try:
        with open(transcript, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or not _is_assistant(row):
                    continue
                message = row.get("message")
                content = message.get("content") if isinstance(message, dict) else row.get("content")
                if isinstance(content, str) and content.strip():
                    last = content
    except OSError:
        return ""
    return last


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
    spec = importlib.util.spec_from_file_location("handback_llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    transcript = resolve_transcript(payload)
    if not transcript:
        print(UNCHECKED, file=sys.stderr)
        return None
    exchange = _exchange(transcript)
    if exchange is None:
        print(UNCHECKED, file=sys.stderr)
        return None
    reply = last_assistant_text(payload, transcript)
    if not reply.strip():
        return None
    dictionary = _phrases().load(HOOK_NAME)
    prompt_text = (
        "ASSISTANT REPLY:\n"
        + reply
        + "\n\nCURRENT TURN TOOL CALLS AND RESULTS (JSONL):\n"
        + exchange
    )
    job = _phrases().job(dictionary, transcript, prompt_text)
    job["id"] = uuid.uuid4().hex
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(
            f"catstack-hook-error {HOOK_NAME}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
