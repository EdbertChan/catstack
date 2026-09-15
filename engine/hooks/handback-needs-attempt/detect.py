from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)
STATE_TTL_SECONDS = 2 * 60 * 60
ON_HIT = (
    "handback-needs-attempt: this reply asks the user to perform a step the agent "
    "could have attempted in this turn. Attempt the command or step first, or name "
    "the permission, sandbox, classifier, or human-only reason that makes it "
    "impossible here."
)


def _message_content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _text_content(data: dict) -> str:
    content = _message_content(data)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _blocks(data: dict) -> list[dict]:
    content = _message_content(data)
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _is_tool_result_line(data: dict) -> bool:
    return any(block.get("type") == "tool_result" for block in _blocks(data))


def parse_lines(raw_lines) -> list[dict]:
    parsed = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def read_transcript(path: str) -> list[dict] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_lines(handle)
    except (OSError, UnicodeError):
        return None


def _is_human_turn_start(data: dict) -> bool:
    role = data.get("type")
    message = data.get("message")
    if role != "user" and not (isinstance(message, dict) and message.get("role") == "user"):
        return False
    return bool(_text_content(data).strip()) and not _is_tool_result_line(data)


def current_turn_lines(lines: list[dict]) -> list[dict]:
    starts = [index for index, data in enumerate(lines) if _is_human_turn_start(data)]
    return lines[starts[-1]:] if starts else lines


def _block_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def exchange_text(reply: str, lines: list[dict]) -> str:
    parts = ["REPLY:", reply.strip(), "TURN TOOL CALLS AND RESULTS:"]
    for data in current_turn_lines(lines):
        for block in _blocks(data):
            if block.get("type") == "tool_use":
                parts.append("TOOL CALL " + json.dumps({
                    "name": block.get("name"),
                    "input": block.get("input"),
                }, ensure_ascii=False, sort_keys=True))
            elif block.get("type") == "tool_result":
                parts.append("TOOL RESULT " + json.dumps({
                    "is_error": block.get("is_error"),
                    "content": _block_text(block),
                }, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    return ""


def last_assistant_text(payload: dict, lines: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for data in reversed(current_turn_lines(lines)):
        message = data.get("message")
        if data.get("type") == "assistant" or (isinstance(message, dict) and message.get("role") == "assistant"):
            text = _text_content(data)
            if text.strip():
                return text
    return ""


def _state_path(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    try:
        return time.time() - os.path.getmtime(_state_path(key)) < STATE_TTL_SECONDS
    except OSError:
        return False


def mark_prompted(key: str) -> None:
    path = _state_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(time.time()))


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


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path:
        return None
    lines = read_transcript(path)
    if lines is None:
        return None
    reply = last_assistant_text(payload, lines)
    if not reply.strip():
        return None
    key = path + "\n" + reply
    if already_prompted(key):
        return None
    dictionary = _phrases().load("handback-needs-attempt")
    job = _phrases().job(dictionary, path, exchange_text(reply, lines))
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        try:
            mark_prompted(key)
        except OSError:
            pass
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(
            f"catstack-hook-error handback-needs-attempt: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
