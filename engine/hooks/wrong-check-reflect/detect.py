from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import re
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

STATE_DIR = os.environ.get(
    "WRONG_CHECK_REFLECT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-wrong-check-reflect"),
)

ALREADY_REFLECT_RE = re.compile(r"(?i)\b/?reflect\b|\b/?automate-me\b|\bautomate me\b")
META_USER_PREFIXES = ("<command-", "<task-notification", "<system")

FOLLOWUP = (
    "Wrong-check admission on this transcript. This is a FAILURE, "
    "not a preference ping: a claim went out before a real check. Finish the "
    "live correction first. Then read the reflect skill and spawn a subagent "
    "for steps 1-4 on this exact transcript. Present Accepted / Backlog / "
    "Route-to-automate-me / Rejected. Do not skip because the task also finished."
)


def _state_file(transcript_path: str) -> str:
    key = transcript_path or "no-transcript"
    digest = hashlib.sha1(os.path.abspath(key).encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(transcript_path: str) -> bool:
    return os.path.isfile(_state_file(transcript_path or "no-transcript"))


def mark_prompted(transcript_path: str) -> None:
    path = _state_file(transcript_path or "no-transcript")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write((transcript_path or "") + "\n")


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _message_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def user_already_asked_reflect(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_user_line(data):
                    continue
                text = _message_text(data)
                if not text or text.lstrip().startswith(META_USER_PREFIXES):
                    continue
                if ALREADY_REFLECT_RE.search(text):
                    return True
    except OSError:
        return False
    return False


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(
                    root, project, "agent-transcripts", conv, f"{conv}.jsonl"
                )
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    return ""


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def last_assistant_from_transcript(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_assistant_line(data):
                    continue
                text = _message_text(data)
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, transcript_path: str = "") -> str:
    for key in (
        "last_assistant_message",
        "last-assistant-message",
        "lastAssistantMessage",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(transcript_path)


def decide(payload: dict) -> str | None:
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


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    text = last_assistant_text(payload, path)
    key = path or text[:200]
    if not text.strip() or already_prompted(key):
        return None
    if path and user_already_asked_reflect(path):
        return None
    dictionary = _phrases().load("wrong-check-reflect")
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception:
        return
