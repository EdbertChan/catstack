"""named-verb-guard: when the user asked for a verb, the reply must show it happened.

Whether the user asked (repro/test/prove, run/show, delete/revert, stop, or a
repeated demand for proof) is judged by the background model from one phrase
dictionary per request type. Whether the reply already carries that type's
evidence is shape only and stays here: a closed fenced block, a `path:line`,
a URL, a markdown table row, a delete/revert command, or no mutating tool call
after the message. A request whose evidence is already present is never sent
to the judge.

Never blocks. A hit arrives on a later turn through the llm-judge inbox.
Fail-open on any read/parse error; `stop_hook_active` skips.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))

import markers  # noqa: E402

PROOF_DEMAND = "named-verb-guard-proof-demand"
PROVE_REQUEST = "named-verb-guard-prove-request"
SHOW_REQUEST = "named-verb-guard-show-request"
DELETE_REQUEST = "named-verb-guard-delete-request"
STOP_REQUEST = "named-verb-guard-stop-request"
CHECKERS = (PROOF_DEMAND, PROVE_REQUEST, SHOW_REQUEST, DELETE_REQUEST, STOP_REQUEST)

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
FILE_LINE_RE = re.compile(r"\b[\w./-]+\.[A-Za-z]{1,5}:\d+\b")
URL_RE = re.compile(r"https?://\S+")
TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
DESTRUCTIVE_CMD_RE = re.compile(
    r"(?:^|\s|\||&&|;)(?:rm|unlink|trash|git\s+(?:rm|revert|reset|restore|checkout|clean|stash))\b",
    re.IGNORECASE,
)
MUTATING_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
MESSAGE_SEPARATOR = "\n\n--- next user message ---\n\n"

SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "<user-prompt-submit-hook",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
)


def _text_of(data: dict) -> str | None:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return None


def _is_human_line(data: dict) -> str | None:
    if not isinstance(data, dict) or data.get("type") != "user":
        return None
    text = _text_of(data)
    if not text or not text.strip():
        return None
    if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if "[Request interrupted by user" in text:
        return None
    return text


def read_transcript(transcript_path: str) -> tuple[list[str], list[dict]]:
    """(all human messages in order, tool_use blocks after the last one)."""
    humans: list[str] = []
    tool_uses: list[dict] = []
    with open(transcript_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _is_human_line(data)
            if text is not None:
                humans.append(text)
                tool_uses = []
                continue
            if not isinstance(data, dict) or data.get("type") != "assistant":
                continue
            message = data.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses.append(block)
    return humans, tool_uses


def has_output_evidence(message: str) -> bool:
    return bool(FENCE_RE.search(message) or FILE_LINE_RE.search(message))


def has_link_evidence(message: str) -> bool:
    return bool(URL_RE.search(message) or TABLE_ROW_RE.search(message))


def bash_commands(tool_uses: list[dict]) -> list[str]:
    out = []
    for block in tool_uses:
        if block.get("name") == "Bash":
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                out.append(command)
    return out


def has_destructive_evidence(message: str, tool_uses: list[dict]) -> bool:
    if any(DESTRUCTIVE_CMD_RE.search(c) for c in bash_commands(tool_uses)):
        return True
    return any(DESTRUCTIVE_CMD_RE.search(c) for c in re.findall(r"`([^`]+)`", message))


def mutating_calls(tool_uses: list[dict]) -> list[str]:
    return [b.get("name") for b in tool_uses if b.get("name") in MUTATING_TOOLS]


def pending_requests(message: str, humans: list[str], tool_uses: list[dict]) -> list[tuple[str, str]]:
    """(checker, text to judge) for each request type whose evidence the reply lacks."""
    if not humans or not humans[-1].strip():
        return []
    if markers.well_formed_tags(message) or message.rstrip().endswith("?"):
        return []
    last = humans[-1]
    output_ok = has_output_evidence(message)
    link_ok = output_ok or has_link_evidence(message)
    pending: list[tuple[str, str]] = []
    if not link_ok and len(humans) >= 2:
        pending.append((PROOF_DEMAND, MESSAGE_SEPARATOR.join(humans)))
    if not output_ok:
        pending.append((PROVE_REQUEST, last))
    if not link_ok:
        pending.append((SHOW_REQUEST, last))
    if not has_destructive_evidence(message, tool_uses):
        pending.append((DELETE_REQUEST, last))
    if mutating_calls(tool_uses):
        pending.append((STOP_REQUEST, last))
    return pending


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


def enqueue_judge(payload: dict) -> list[str]:
    """Enqueue one judge job per request type whose evidence is missing; return job ids."""
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return []
    message = payload.get("last_assistant_message") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return []
    humans, tool_uses = read_transcript(transcript_path)
    job_ids: list[str] = []
    for checker, text in pending_requests(message, humans, tool_uses):
        dictionary = _phrases().load(checker)
        job = _phrases().job(dictionary, transcript_path, text)
        job["id"] = uuid.uuid4().hex
        job_ids.append(_judge().enqueue(job))
    return job_ids


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error named-verb-guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
