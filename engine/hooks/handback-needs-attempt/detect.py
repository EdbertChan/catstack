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
CHECKER = "handback-needs-attempt"

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_flags"))
from flags import enforcement_gate


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _judge():
    return _load(LLM_JUDGE_PATH, "handback_llm_judge")


@functools.cache
def _phrases():
    return _load(PHRASES_PATH, "handback_llm_judge_phrases")


def _is_tool_result(data):
    if data.get("toolUseResult") is not None:
        return True
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_harness(data):
    return bool(data.get("isMeta") or data.get("isSidechain") or data.get("is_sidechain") or data.get("agentId") or data.get("agent_id"))


def _is_human(data):
    if _is_harness(data) or _is_tool_result(data):
        return False
    message = data.get("message")
    role = message.get("role") if isinstance(message, dict) else data.get("type")
    return role == "user"


def _content(data):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _parse_lines(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _turn_lines(lines):
    start = 0
    for index in range(len(lines) - 1, -1, -1):
        if isinstance(lines[index], dict) and _is_human(lines[index]):
            start = index
            break
    return lines[start:]


def _typed_refusal(value):
    if isinstance(value, dict):
        if value.get("permissionDenied") is True or value.get("permission_denied") is True:
            return True
        if value.get("toolDenialKind") in {"user-rejected", "permission-denied", "hook-refusal"}:
            return True
        if value.get("permission") == "deny" or value.get("permissionDecision") == "deny":
            return True
        if value.get("rejected") is True or value.get("refused") is True:
            return True
        return any(_typed_refusal(item) for item in value.values())
    if isinstance(value, list):
        return any(_typed_refusal(item) for item in value)
    return False


def turn_has_typed_refusal(lines):
    return any(_typed_refusal(line) for line in _turn_lines(lines))


def _exchange(reply, lines):
    parts = ["ASSISTANT REPLY:\n" + reply]
    for data in _turn_lines(lines):
        content = _content(data)
        if isinstance(content, list) and any(isinstance(block, dict) and block.get("type") in {"tool_use", "tool_result"} for block in content):
            parts.append(json.dumps(data, ensure_ascii=False, sort_keys=True))
        elif _is_human(data):
            parts.append("HUMAN TURN:\n" + json.dumps(content, ensure_ascii=False))
    return "\n\n".join(parts)


def _lines_from_payload(payload):
    provided = payload.get("transcript_lines")
    if isinstance(provided, list):
        return provided
    path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not isinstance(path, str) or not path:
        raise OSError("payload has no transcript path")
    return _parse_lines(path)


def decide(payload):
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("stop_hook_active"):
        return None
    reply = payload.get("last_assistant_message")
    if not isinstance(reply, str) or not reply.strip():
        return None
    lines = _lines_from_payload(payload)
    if turn_has_typed_refusal(lines):
        return None
    return _exchange(reply, lines)


def enqueue_judge(payload: dict, stderr=None) -> str | None:
    payload = payload if isinstance(payload, dict) else {}
    if not enforcement_gate(CHECKER, payload.get("cwd")):
        return None
    path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    reply = payload.get("last_assistant_message")
    if not isinstance(reply, str) or not path:
        (stderr or sys.stderr).write(f"catstack-hook-unchecked {CHECKER}: payload has no reply text or transcript path\n")
        return None
    try:
        exchange = decide(payload)
    except (OSError, ValueError, TypeError) as exc:
        (stderr or sys.stderr).write(f"catstack-hook-unchecked {CHECKER}: could not read transcript: {exc}\n")
        return None
    if exchange is None:
        return None
    dictionary = _phrases().load(CHECKER)
    job = _phrases().job(dictionary, path, exchange)
    job["id"] = uuid.uuid4().hex
    return _judge().enqueue(job)


def try_enqueue_judge(payload):
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error {CHECKER}: {type(exc).__name__}: {exc}", file=sys.stderr)
