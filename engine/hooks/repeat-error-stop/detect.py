"""Shared detector + state for repeat-error-stop.

A failed tool call (Claude: PostToolUseFailure; elsewhere: a non-zero exit
code or tool error marker in the result) is reduced to a signature (error lines
with numbers, hashes, quoted names, and paths blanked out). The third time
the same signature shows up in one session the harness is told to stop
re-running and report; re-running any command that produced that signature
is denied until the human sends a new prompt.

Fail-open: every public function swallows IO/parse errors.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

STATE_DIR = os.environ.get(
    "REPEAT_ERROR_STOP_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-repeat-error-stop"),
)
THRESHOLD = int(os.environ.get("REPEAT_ERROR_STOP_THRESHOLD", "3") or 3)
TTL_SECONDS = 24 * 3600

ERROR_LINE_RE = re.compile(
    r"(\berror\b|\bfail(ed|ure|ing)?\b|\bfatal\b|timed? ?out|did not reach|\bconflict\b|"
    r"traceback|exception|\benoent\b|\beaddrinuse\b|\b429\b|rate.?limit|not found|"
    r"denied|could not|cannot|unable to|exit code [1-9]|command exited with|\bpanic\b)",
    re.I,
)
SUCCESS_ONLY_RE = re.compile(r"^\s*(0 (errors?|failures?)|no errors?|tests? passed|passed)\b", re.I)

_NORMALIZERS = (
    (re.compile(r"\b[0-9a-f]{7,}\b", re.I), "<hex>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}[:\d.z+-]*", re.I), "<ts>"),
    (re.compile(r"(\"[^\"]*\"|'[^']*'|`[^`]*`)"), "<q>"),
    (re.compile(r"(/[\w.@+-]+){2,}"), "<path>"),
    (re.compile(r"\d+"), "N"),
    (re.compile(r"\s+"), " "),
)

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace", "Delete", "apply_patch", "edit_file")
RESET_ON_EDIT = os.environ.get("REPEAT_ERROR_STOP_RESET_ON_EDIT", "1") == "1"

AUTOMATED_PROMPT_MARKERS = (
    "<task-notification",
    "[system notification",
    "<command-name>/loop</command-name>",
    "<<autonomous-loop",
)


def _session_key(payload: dict) -> str:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "transcript_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("/", "_")[-80:]
    cwd = payload.get("cwd") or payload.get("workspace_roots") or "default"
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else "default"
    return str(cwd).replace("/", "_")[-80:]


def state_path(payload: dict) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"{_session_key(payload)}.json")


def load_state(payload: dict) -> dict[str, Any]:
    try:
        with open(state_path(payload)) as f:
            data = json.load(f)
        if isinstance(data, dict):
            if time.time() - float(data.get("updated_at") or 0) > TTL_SECONDS:
                return {}
            return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def save_state(payload: dict, state: dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    try:
        path = state_path(payload)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def reset_state(payload: dict) -> None:
    try:
        os.remove(state_path(payload))
    except OSError:
        pass


def normalize(text: str) -> str:
    out = (text or "").strip().lower()
    for rx, rep in _NORMALIZERS:
        out = rx.sub(rep, out)
    return out[:300]


def tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def _flatten(value: Any, depth: int = 0) -> str:
    if depth > 3 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key in ("stderr", "stdout", "error", "content", "output", "text", "message", "result"):
            if key in value:
                parts.append(_flatten(value[key], depth + 1))
        if not parts:
            parts = [_flatten(v, depth + 1) for v in value.values()]
        return "\n".join(p for p in parts if p)
    if isinstance(value, list):
        return "\n".join(_flatten(v, depth + 1) for v in value)
    return str(value)


def tool_result_text(payload: dict) -> str:
    for key in ("error", "tool_response", "tool_result", "toolResult", "result", "output", "stdout", "stderr"):
        if key in payload:
            text = _flatten(payload.get(key))
            if text:
                return text
    return ""


EXIT_CODE_RE = re.compile(r"^\s*exit code (\d+)\b", re.I | re.M)
FAILURE_MARKERS = ("<tool_use_error>", "permission for this action was denied", "did not reach status")
OBSERVED = os.environ.get("REPEAT_ERROR_STOP_OBSERVED", "1") == "1"
STRONG_ERROR_RE = re.compile(
    r"(^\s*(error|fatal|traceback|panic)\b|\berror:|\bfailed:|^\s*(✗|✘|×|\[error\]|fail\b(?! 0))|did not reach status|"
    r"test timeout|timed out|\b(enoent|eaddrinuse|econnrefused|econnreset)\b|^\s*exit code [1-9])",
    re.I | re.M,
)


def failure_text(payload: dict) -> str | None:
    """Return the failure text, or None when this tool call did not fail.

    Claude Code only fires PostToolUseFailure for failed calls (payload["error"]
    = "Exit code N\n<stderr>"); PostToolUse fires on success. Other harnesses and
    the transcript backtest fall back to explicit failure markers in the text.
    """
    if payload.get("is_interrupt"):
        return None
    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
    if event == "PostToolUseFailure" or payload.get("is_error") or payload.get("isError"):
        return tool_result_text(payload) or "tool failed"
    text = tool_result_text(payload)
    if not text:
        return None
    match = EXIT_CODE_RE.search(text[:200])
    if match and match.group(1) != "0":
        return text
    lowered = text[:400].lower()
    if any(marker in lowered for marker in FAILURE_MARKERS):
        return text
    if OBSERVED:
        for line in text.splitlines():
            if "throw new" not in line and STRONG_ERROR_RE.search(line):
                return text
    return None


def error_lines(text: str) -> list[str]:
    candidates = [line.strip() for line in (text or "").splitlines()]
    candidates = [line for line in candidates if line and not EXIT_CODE_RE.match(line) and not SUCCESS_ONLY_RE.match(line) and "throw new" not in line]
    picked = [line[:400] for line in candidates if ERROR_LINE_RE.search(line)][:2]
    if not picked:
        picked = [line[:400] for line in candidates[:2]]
    return picked


def error_signature(text: str, command: str = "") -> tuple[str, str] | None:
    if text is None:
        return None
    lines = error_lines(text)
    exit_match = EXIT_CODE_RE.search(text[:200])
    exit_code = exit_match.group(1) if exit_match else ""
    if not lines:
        if not exit_code:
            return None
        lines = [f"exit code {exit_code}"]
        normalized = f"exit code {exit_code} :: {normalize(command)}"
    else:
        normalized = " || ".join(normalize(line) for line in lines)
    digest = hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()[:12]
    return digest, lines[0]


def command_signature(payload: dict) -> str:
    ti = tool_input(payload)
    for key in ("command", "cmd", "script"):
        if isinstance(ti.get(key), str) and ti[key].strip():
            return normalize(ti[key])[:200]
    return ""


def note_edit(payload: dict) -> None:
    """A successful edit means the next identical failure is a new attempt, not a blind re-run."""
    state = load_state(payload)
    state["edit_epoch"] = int(state.get("edit_epoch", 0)) + 1
    save_state(payload, state)


def record_result(payload: dict) -> tuple[bool, str]:
    """Record one tool outcome. Returns (should_block, reason)."""
    text = failure_text(payload)
    if text is None:
        if RESET_ON_EDIT and tool_name(payload) in EDIT_TOOLS:
            note_edit(payload)
        return False, ""
    sig = error_signature(text, command_signature(payload))
    if sig is None:
        return False, ""
    digest, sample = sig
    state = load_state(payload)
    errors = state.setdefault("errors", {})
    entry = errors.get(digest) or {"count": 0, "sample": sample, "commands": [], "first_at": time.time()}
    epoch = int(state.get("edit_epoch", 0))
    if RESET_ON_EDIT and entry.get("epoch", epoch) != epoch:
        entry["count"] = 0
        entry["commands"] = []
    entry["epoch"] = epoch
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_at"] = time.time()
    cmd = command_signature(payload)
    if cmd and cmd not in entry["commands"]:
        entry["commands"] = (entry["commands"] + [cmd])[-20:]
    errors[digest] = entry
    if entry["count"] >= THRESHOLD:
        state.setdefault("blocked", {})[digest] = True
    save_state(payload, state)
    if entry["count"] >= THRESHOLD:
        return True, block_reason(entry)
    return False, ""


def block_reason(entry: dict) -> str:
    return (
        f"repeat-error-stop: the same error has now occurred {entry.get('count')} times in this session:\n"
        f"    {entry.get('sample', '')[:300]}\n"
        "Do not re-run it. Stop and report to the user: the error verbatim, what you tried, and what "
        "you have ruled out. If you continue, state a new hypothesis first and run a different command; "
        "re-running any command that produced this error is denied until the user sends a new prompt."
    )


def tool_block_reason(payload: dict) -> tuple[bool, str]:
    """PreToolUse: deny a command that already produced a blocked error signature."""
    state = load_state(payload)
    blocked = state.get("blocked") or {}
    if not blocked:
        return False, ""
    cmd = command_signature(payload)
    if not cmd:
        return False, ""
    for digest in blocked:
        entry = (state.get("errors") or {}).get(digest) or {}
        if cmd in (entry.get("commands") or []):
            return True, block_reason(entry) + "\n(denied: this exact command already failed this way.)"
    return False, ""


def is_automated_prompt(prompt: str) -> bool:
    lowered = (prompt or "").strip().lower()
    return any(marker in lowered for marker in AUTOMATED_PROMPT_MARKERS)


def handle_prompt(payload: dict) -> bool:
    """UserPromptSubmit: a fresh human prompt clears the counters. Returns True if reset."""
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or payload.get("text") or "")
    if is_automated_prompt(prompt):
        return False
    reset_state(payload)
    return True
