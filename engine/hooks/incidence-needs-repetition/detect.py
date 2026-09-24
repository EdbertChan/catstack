"""Judge whether an assistant reply claims behavior across runs."""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import time
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
SDK_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from events import write_events  # noqa: E402
from finding import Finding  # noqa: E402
from modes import effective_mode  # noqa: E402

HOOK = "incidence-needs-repetition"
RULE_ALWAYS_CLAIM = "incidence-needs-repetition.always-claim"
WAIT_ENV = "CATSTACK_INCIDENCE_NEEDS_REPETITION_WAIT_SECONDS"
DEFAULT_WAIT_SECONDS = 40.0
POLL_SECONDS = 0.1
UNCHECKED_MESSAGE = (
    "incidence-needs-repetition: unchecked, letting this reply through: {why}. "
    "A late verdict will still arrive through the llm-judge inbox."
)


def parse_lines(raw_lines) -> list[dict]:
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    message = data.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, list):
        return any(isinstance(part, dict) and part.get("type") == "text" for part in content)
    return isinstance(content, str) and bool(content.strip())


def repeated_command_this_turn(lines: list[dict]) -> bool:
    """True when one Bash command ran two or more times since the last human turn."""
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    seen: dict[str, int] = {}
    for data in lines[turn_start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        if not isinstance(message, dict):
            continue
        for part in message.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            if part.get("name") != "Bash":
                continue
            command = (part.get("input") or {}).get("command")
            if not isinstance(command, str):
                continue
            key = " ".join(command.split())
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 2:
                return True
    return False


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


def decide_from_lines(_message: str, _lines: list[dict]) -> None:
    return None


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


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    supplied_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
    )
    path = resolve_transcript(payload)
    if isinstance(supplied_path, str) and supplied_path and not path:
        return None
    text = last_assistant_text(payload, path)
    if not text.strip():
        return None
    lines: list[dict] = []
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    if repeated_command_this_turn(lines):
        return None
    dictionary = _phrases().load("incidence-needs-repetition")
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    job["rule_id"] = RULE_ALWAYS_CLAIM
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error incidence-needs-repetition: {type(exc).__name__}: {exc}", file=sys.stderr)
        return


def detect(event: dict[str, object]) -> list[Finding]:
    if not isinstance(event, dict):
        return []
    try:
        mode, mode_source = effective_mode(HOOK, event)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: mode unchecked ({type(exc).__name__}: {exc})", file=sys.stderr)
        return []
    if mode == "off":
        return []
    try:
        check = _check_reply(event)
        if check is None:
            return []
        text, path, dictionary = check
        job = _phrases().job(dictionary, path, text)
        job["id"] = uuid.uuid4().hex
        job["rule_id"] = RULE_ALWAYS_CLAIM
        seconds = wait_seconds()
        job["timeout_seconds"] = seconds
        job_id = _judge().enqueue(job)
        if job_id is None:
            return []
        outcome, verdict = wait_for_verdict(path, job_id, seconds)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    if outcome == "hit":
        answer = verdict.get("answer") if isinstance(verdict, dict) else None
        evidence = json.dumps(answer, sort_keys=True) if isinstance(answer, dict) else str(verdict.get("reason") or "")
        return [
            Finding(
                rule_id=RULE_ALWAYS_CLAIM,
                subject=_subject(text),
                message=dictionary["on_hit"],
                evidence=evidence,
            )
        ]
    if outcome == "unchecked":
        reason = str(verdict.get("reason") or "the judge gave no answer in time")
        _record_unchecked(event, text, reason, mode, mode_source)
        print(UNCHECKED_MESSAGE.format(why=reason), file=sys.stderr)
    return []


def _check_reply(payload: dict[str, object]) -> tuple[str, str, dict] | None:
    if payload.get("stop_hook_active"):
        return None
    supplied_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
    )
    path = resolve_transcript(payload)
    if isinstance(supplied_path, str) and supplied_path and not path:
        return None
    text = last_assistant_text(payload, path)
    if not text.strip():
        return None
    lines: list[dict] = []
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    if repeated_command_this_turn(lines):
        return None
    return text, path, _phrases().load(HOOK)


def wait_seconds() -> float:
    raw = os.environ.get(WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        print(f"{HOOK}: {WAIT_ENV}={raw!r} is not a number; waiting {DEFAULT_WAIT_SECONDS}s", file=sys.stderr)
        return DEFAULT_WAIT_SECONDS


def wait_for_verdict(transcript: str, job_id: str, seconds: float) -> tuple[str, dict]:
    deadline = time.monotonic() + seconds
    while True:
        verdict = take_verdict(transcript, job_id)
        if verdict is not None:
            return str(verdict.get("outcome") or "unchecked"), verdict
        if time.monotonic() >= deadline:
            return "unchecked", {
                "id": job_id,
                "outcome": "unchecked",
                "reason": "the judge gave no answer in time",
            }
        time.sleep(POLL_SECONDS)


def take_verdict(transcript: str, job_id: str) -> dict | None:
    judge = _judge()
    path = os.path.join(judge.verdict_dir(transcript), f"{job_id}.json")
    taken = f"{path}.{os.getpid()}.taken"
    try:
        os.rename(path, taken)
    except FileNotFoundError:
        return None
    try:
        with open(taken, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        loaded = {"id": job_id, "outcome": "unchecked", "reason": f"unreadable verdict file: {exc}"}
    finally:
        try:
            os.remove(taken)
        except OSError as exc:
            print(f"{HOOK}: could not remove {taken}: {exc}", file=sys.stderr)
    return loaded if isinstance(loaded, dict) else {"id": job_id, "outcome": "unchecked", "reason": "verdict is not an object"}


def _record_unchecked(event: dict[str, object], text: str, reason: str, mode: str, mode_source: str) -> None:
    finding = Finding(
        rule_id=RULE_ALWAYS_CLAIM,
        subject=_subject(text),
        message=UNCHECKED_MESSAGE.format(why=reason),
        evidence=reason,
    )
    write_events(HOOK, "claude", event, [finding], mode, mode_source, 0, action="unchecked")


def _subject(text: str) -> str:
    return "reply:" + uuid.uuid5(uuid.NAMESPACE_URL, text).hex
