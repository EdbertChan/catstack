from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_flags"))

from flags import enforcement_gate

CHECKER = "handback-needs-attempt"
MAX_EVENT_TEXT = 3000


def _message_content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _message_text(data: dict) -> str:
    content = _message_content(data)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def _is_tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None or data.get("toolDenialKind") is not None:
        return True
    content = _message_content(data)
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_human_turn_start(data: dict) -> bool:
    message = data.get("message")
    role = message.get("role") if isinstance(message, dict) else data.get("type")
    return (
        role == "user"
        and not _is_tool_result(data)
        and not data.get("isMeta")
        and not data.get("isSidechain")
        and not data.get("agentId")
        and not data.get("agent_id")
    )


def _read_transcript(path: str) -> list[dict] | None:
    if not path or not os.path.isfile(path):
        return None
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
    except OSError:
        return None
    return rows


def _tool_call_text(block: dict) -> str:
    name = block.get("name") or "tool"
    tool_id = block.get("id") or block.get("tool_use_id") or ""
    detail = block.get("input")
    if not isinstance(detail, (dict, list, str, int, float, bool)) and detail is not None:
        detail = str(detail)
    label = f"Tool call {name}"
    if tool_id:
        label += f" ({tool_id})"
    return f"{label}: {json.dumps(detail, ensure_ascii=False, sort_keys=True)}"


def _tool_result_text(block: dict, data: dict) -> str:
    tool_id = block.get("tool_use_id") or block.get("id") or ""
    label = "Tool result"
    if tool_id:
        label += f" ({tool_id})"
    fields = {key: value for key, value in data.items() if key in ("toolUseResult", "toolDenialKind")}
    if fields:
        return f"{label}: {json.dumps(fields, ensure_ascii=False, sort_keys=True)} {json.dumps(block.get('content'), ensure_ascii=False)}"
    return f"{label}: {json.dumps(block.get('content'), ensure_ascii=False)}"


def turn_exchange(path: str, reply: str) -> str | None:
    rows = _read_transcript(path)
    if rows is None:
        return None
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if _is_human_turn_start(rows[index]):
            start = index + 1
            break
    events = []
    for data in rows[start:]:
        if data.get("type") == "assistant" or (
            isinstance(data.get("message"), dict) and data["message"].get("role") == "assistant"
        ):
            content = _message_content(data)
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    events.append(_tool_call_text(block)[:MAX_EVENT_TEXT])
        elif _is_tool_result(data):
            content = _message_content(data)
            blocks = content if isinstance(content, list) else [{"content": content}]
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    events.append(_tool_result_text(block, data)[:MAX_EVENT_TEXT])
            if not isinstance(content, list) and data.get("toolUseResult") is not None:
                events.append(_tool_result_text({"content": data.get("toolUseResult")}, data)[:MAX_EVENT_TEXT])
    tools = "\n".join(events) if events else "none"
    return f"Tool calls and results this turn:\n{tools}\n\nLast assistant reply:\n{reply}"


def resolve_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and os.path.isfile(value):
            return value
    return ""


def last_assistant_from_transcript(path: str) -> str:
    rows = _read_transcript(path)
    if rows is None:
        return ""
    last = ""
    for data in rows:
        message = data.get("message")
        role = message.get("role") if isinstance(message, dict) else data.get("type")
        if role == "assistant":
            text = _message_text(data)
            if text.strip():
                last = text
    return last


def last_assistant_text(payload: dict, path: str) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(path)


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge_handback", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases_handback", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict, harness: str = "unknown", stderr=None) -> str | None:
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("stop_hook_active"):
        return None
    if not enforcement_gate(CHECKER, payload.get("cwd"), stderr=stderr or sys.stderr):
        return None
    path = resolve_transcript(payload)
    reply = last_assistant_text(payload, path)
    if not path or not reply.strip():
        (stderr or sys.stderr).write(
            f"catstack-hook-unchecked {CHECKER}: missing readable transcript or assistant reply\n"
        )
        return None
    exchange = turn_exchange(path, reply)
    if exchange is None:
        (stderr or sys.stderr).write(
            f"catstack-hook-unchecked {CHECKER}: transcript could not be read\n"
        )
        return None
    dictionary = _phrases().load(CHECKER)
    job = _phrases().job(dictionary, path, exchange)
    job["id"] = uuid.uuid4().hex
    job["harness"] = harness
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict, harness: str = "unknown") -> None:
    try:
        enqueue_judge(payload, harness)
    except Exception as exc:
        print(f"catstack-hook-error {CHECKER}: {type(exc).__name__}: {exc}", file=sys.stderr)
