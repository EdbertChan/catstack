from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
HOOK = "handback-needs-attempt"


def _message(data: dict) -> dict:
    value = data.get("message")
    return value if isinstance(value, dict) else {}


def _content(data: dict) -> object:
    message = _message(data)
    return message.get("content", data.get("content"))


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in value
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _is_tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None:
        return True
    content = _content(data)
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "tool_result" for part in content
    )


def _is_human(data: dict) -> bool:
    if data.get("type") != "user" or data.get("isMeta") or data.get("isSidechain"):
        return False
    if data.get("agentId") or data.get("agent_id") or _is_tool_result(data):
        return False
    return bool(_text(_content(data)).strip())


def _is_assistant(data: dict) -> bool:
    return (
        not data.get("isSidechain")
        and not data.get("agentId")
        and not data.get("agent_id")
        and (data.get("type") == "assistant" or _message(data).get("role") == "assistant")
    )


def _read_lines(path: str) -> list[dict] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            rows = []
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
            return rows
    except OSError as exc:
        print(f"catstack-hook-error {HOOK}: transcript unchecked: {exc}", file=sys.stderr)
        return None


def _turn_rows(rows: list[dict]) -> list[dict]:
    start = 0
    for index, row in enumerate(rows):
        if _is_human(row):
            start = index
    return rows[start:]


def _tool_events(rows: list[dict]) -> list[dict]:
    events = []
    for row in _turn_rows(rows):
        if _is_assistant(row):
            for part in _content(row) if isinstance(_content(row), list) else []:
                if not isinstance(part, dict) or part.get("type") != "tool_use":
                    continue
                events.append({
                    "kind": "tool_call",
                    "id": part.get("id"),
                    "name": part.get("name"),
                    "input": part.get("input"),
                })
        elif _is_tool_result(row):
            for part in _content(row) if isinstance(_content(row), list) else []:
                if not isinstance(part, dict) or part.get("type") != "tool_result":
                    continue
                events.append({
                    "kind": "tool_result",
                    "tool_use_id": part.get("tool_use_id"),
                    "is_error": part.get("is_error"),
                    "content": _text(part.get("content")),
                })
    return events


def resolve_transcript(payload: dict) -> str:
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def last_assistant_from_transcript(rows: list[dict]) -> str:
    for row in reversed(rows):
        if _is_assistant(row):
            text = _text(_content(row))
            if text.strip():
                return text
    return ""


def last_assistant_text(payload: dict, rows: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(rows)


def exchange_text(reply: str, events: list[dict]) -> str:
    encoded = json.dumps(events, ensure_ascii=False, sort_keys=True)
    return f"TURN TOOL CALLS AND RESULTS:\n{encoded if events else '(none recorded)'}\nLATEST ASSISTANT REPLY:\n{reply}"


def decide(_payload: dict) -> None:
    return None


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


def enqueue_judge(payload: dict, harness: str = "unknown") -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path or not os.path.isfile(path):
        print(f"catstack-hook-error {HOOK}: transcript is unreadable; reply is unchecked", file=sys.stderr)
        return None
    rows = _read_lines(path)
    if rows is None:
        return None
    reply = last_assistant_text(payload, rows)
    if not reply.strip():
        return None
    dictionary = _phrases().load(HOOK)
    job = _phrases().job(dictionary, path, exchange_text(reply, _tool_events(rows)))
    job["id"] = uuid.uuid4().hex
    job["harness"] = harness
    job_id = _judge().enqueue(job)
    if job_id is None:
        print(f"catstack-hook-error {HOOK}: judge could not run; reply is unchecked", file=sys.stderr)
    return job_id


def try_enqueue_judge(payload: dict, harness: str = "unknown") -> None:
    try:
        enqueue_judge(payload, harness)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: {type(exc).__name__}: {exc}", file=sys.stderr)
