from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HERE), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
STATE_DIR = os.environ.get(
    "HANDBACK_NEEDS_ATTEMPT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-handback-needs-attempt"),
)
STATE_TTL_SECONDS = 7200
FOLLOWUP = (
    "handback-needs-attempt: this reply hands the user a step the agent could have attempted. "
    "Attempt the command first, or name the permission refusal or human-only step that prevents it."
)
UNCHECKED = "handback-needs-attempt: unchecked, letting this reply through: {reason}"


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(root, project, "agent-transcripts", conv.strip(), f"{conv.strip()}.jsonl")
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    return ""


def _message_content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _text_content(data: dict) -> str:
    content = _message_content(data)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _is_tool_result(data: dict) -> bool:
    content = _message_content(data)
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_human_user(data: dict) -> bool:
    if data.get("type") != "user" or _is_tool_result(data):
        return False
    return not data.get("isMeta") and not data.get("isSidechain") and bool(_text_content(data).strip())


def read_transcript(path: str) -> list[dict] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            rows = []
            for line in handle:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("transcript row is not an object")
                rows.append(data)
            return rows
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def _assistant_text(data: dict) -> str:
    if data.get("type") == "assistant":
        return _text_content(data)
    message = data.get("message")
    return _text_content(data) if isinstance(message, dict) and message.get("role") == "assistant" else ""


def last_assistant_text(payload: dict, rows: list[dict]) -> str:
    for key in ("last_assistant_message", "last-assistant-message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for row in reversed(rows):
        text = _assistant_text(row)
        if text.strip():
            return text
    return ""


def _tool_block(block: dict, label: str) -> str:
    if block.get("type") == "tool_use":
        return f"TOOL CALL {block.get('name', '')}: {json.dumps(block.get('input') or {}, ensure_ascii=False)}"
    content = block.get("content", "")
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    error = " error=true" if block.get("is_error") else ""
    return f"TOOL RESULT {block.get('tool_use_id', '')}{error}: {content}"


def current_turn_exchange(rows: list[dict], reply: str) -> str:
    start = 0
    for index, row in enumerate(rows):
        if _is_human_user(row):
            start = index
    parts = [f"REPLY:\n{reply}", "TURN TOOL CALLS AND RESULTS:"]
    found = False
    for row in rows[start:]:
        content = _message_content(row)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in ("tool_use", "tool_result"):
                continue
            found = True
            parts.append(_tool_block(block, row.get("type", "")))
    if not found:
        parts.append("none")
    return "\n".join(parts)


def reply_key(transcript_path: str, text: str, exchange: str = "") -> str:
    base = os.path.abspath(transcript_path) if transcript_path else "no-transcript"
    digest = hashlib.sha256((text or "").encode("utf-8") + b"\0" + (exchange or "").encode("utf-8")).hexdigest()
    return base + "\n" + digest


def _state_file(key: str) -> str:
    digest = hashlib.sha1((key or "no-transcript").encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    path = _state_file(key or "no-transcript")
    try:
        modified = os.path.getmtime(path)
    except OSError:
        return False
    now = time.time()
    if modified > now or now - modified > STATE_TTL_SECONDS:
        return False
    return True


def mark_prompted(key: str) -> None:
    path = _state_file(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")


def _transcript_problem(payload: dict, path: str) -> str:
    supplied = payload.get("agent_transcript_path") or payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(supplied, str) and supplied and not path:
        return f"the transcript could not be read ({supplied!r})"
    if not path:
        return "the payload names no transcript"
    return ""


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
        return None
    rows = read_transcript(path)
    if rows is None:
        return None
    reply = last_assistant_text(payload, rows)
    if not reply.strip():
        return None
    exchange = current_turn_exchange(rows, reply)
    key = reply_key(path, reply, exchange)
    if already_prompted(key):
        return None
    dictionary = _phrases().load("handback-needs-attempt")
    job = _phrases().job(dictionary, path, exchange)
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        if not isinstance(payload, dict) or payload.get("stop_hook_active"):
            return
        path = resolve_transcript(payload)
        problem = _transcript_problem(payload, path)
        if problem:
            sys.stderr.write(UNCHECKED.format(reason=problem) + "\n")
            return
        if read_transcript(path) is None:
            sys.stderr.write(UNCHECKED.format(reason=f"the transcript could not be read ({path!r})") + "\n")
            return
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error handback-needs-attempt: {type(exc).__name__}: {exc}", file=sys.stderr)


def decide(payload: dict) -> str | None:
    return None
