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
HOOK_NAME = "handback-needs-attempt"


def _message(data: dict) -> dict:
    message = data.get("message")
    return message if isinstance(message, dict) else data


def _blocks(data: dict) -> list[dict]:
    content = _message(data).get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _text(data: dict) -> str:
    content = _message(data).get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in _blocks(data):
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _tool_result_text(data: dict) -> str:
    values = []
    for block in _blocks(data):
        if block.get("type") != "tool_result":
            continue
        content = block.get("content")
        if isinstance(content, str):
            values.append(content)
        elif isinstance(content, list):
            values.extend(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
    return "\n".join(value for value in values if value)


def _tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None:
        return True
    return any(block.get("type") == "tool_result" for block in _blocks(data))


def _user(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    return _message(data).get("role") == "user"


def _assistant(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    return _message(data).get("role") == "assistant"


def _meta(data: dict) -> bool:
    return bool(data.get("isMeta") or data.get("isSidechain") or data.get("agentId"))


def _render(data: dict) -> list[str]:
    if _meta(data):
        return []
    if _tool_result(data):
        value = _tool_result_text(data) or _text(data)
        if not value:
            value = json.dumps(data.get("toolUseResult"), ensure_ascii=False)
        return [f"TOOL RESULT:\n{value}"]
    if _assistant(data):
        rendered = []
        for block in _blocks(data):
            if block.get("type") == "tool_use":
                rendered.append(
                    "TOOL CALL:\n"
                    + json.dumps(
                        {"name": block.get("name"), "input": block.get("input")},
                        ensure_ascii=False,
                    )
                )
            elif block.get("type") == "text" and block.get("text"):
                rendered.append(f"ASSISTANT:\n{block['text']}")
        return rendered
    if _user(data):
        value = _text(data)
        return [f"USER:\n{value}"] if value else []
    return []


def _human_user(data: dict) -> bool:
    return _user(data) and not _tool_result(data) and not _meta(data)


def _transcript_exchange(path: str) -> str | None:
    if not path:
        print(
            f"catstack-hook-error {HOOK_NAME}: unchecked because no transcript was supplied",
            file=sys.stderr,
        )
        return None
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
    except OSError as exc:
        print(
            f"catstack-hook-error {HOOK_NAME}: unchecked because transcript {path} could not be read: {exc}",
            file=sys.stderr,
        )
        return None
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if _human_user(rows[index]):
            start = index
            break
    rendered = []
    for data in rows[start:]:
        rendered.extend(_render(data))
    return "\n\n".join(rendered)


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str) and os.path.isfile(agent):
        return agent
    for key in ("transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def last_assistant_from_transcript(path: str) -> str:
    if not path:
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and _assistant(data) and not _meta(data):
                    text = _text(data).strip()
                    if text:
                        last = text
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, path: str) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(path)


def decide(payload: dict) -> str | None:
    return None


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
    path = resolve_transcript(payload)
    exchange = _transcript_exchange(path)
    if exchange is None:
        return None
    reply = last_assistant_text(payload, path)
    if not reply.strip():
        return None
    dictionary = _phrases().load(HOOK_NAME)
    text = f"TURN EXCHANGE:\n{exchange}\n\nASSISTANT REPLY:\n{reply}"
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(
            f"catstack-hook-error {HOOK_NAME}: unchecked because judge setup failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
