"""Catch a specific thrash pattern: asserting a remote-host restart is
low-risk/safe using only one signal.

Found via /reflect on an Invoker session (2026-08-22): the agent said
"restart risk is low" for a DigitalOcean droplet after only checking the
workflow queue, while a same-day hotfix backup file it had already seen on
that host went unconnected. No restart actually happened that time, but
the gap was real -- a shared remote host can have live logins or in-flight
work a queue check alone won't show.

Fail-open on read/parse errors: a broken hook must never brick a session.
The decision itself (block when evidence is thin) is intentional, not an
error path.
"""
from __future__ import annotations

import json
import re

RESTART_WORD_RE = re.compile(r"\brestart(?:ing|ed)?\b", re.IGNORECASE)
SAFETY_PHRASE_RE = re.compile(
    r"\b(?:low[- ]risk|risk is low|is safe|safe to|minimal risk)\b",
    re.IGNORECASE,
)
REMOTE_HOST_RE = re.compile(
    r"\b(?:ssh|remote|droplet|digital\s*ocean|do-?\d+|remoteTargets|remote_digital_ocean)\b",
    re.IGNORECASE,
)

QUEUE_CHECK_RE = re.compile(
    r"query\s+(?:workflows?|tasks?|queue)|workflow.{0,20}queue|task.{0,20}queue|running\s+workflows?",
    re.IGNORECASE,
)
SESSION_CHECK_RE = re.compile(
    r"(?<![\w/-])(?:who|w|last|users)(?![\w/-])|loginctl|logged.{0,10}in|active\s+sessions?",
    re.IGNORECASE,
)

PROXIMITY_WINDOW = 200  # chars between a restart word and a safety phrase


def claims_restart_is_safe(message: str) -> bool:
    if not message or not REMOTE_HOST_RE.search(message):
        return False
    restart_positions = [m.start() for m in RESTART_WORD_RE.finditer(message)]
    if not restart_positions:
        return False
    for safety_match in SAFETY_PHRASE_RE.finditer(message):
        for pos in restart_positions:
            if abs(safety_match.start() - pos) <= PROXIMITY_WINDOW:
                return True
    return False


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(parts)
    return ""


def bash_commands_this_turn(transcript_path: str) -> list[str]:
    """Bash-tool command strings from the current turn: from the last real
    (non-tool-result, non-notification) user message to end of file."""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []

    turn_start = 0
    for i, raw in enumerate(lines):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not _is_user_line(data):
            continue
        text = _text_content(data)
        if not text.strip():
            continue  # tool_result-only entry, not an authored user turn
        if text.lstrip().startswith(("<command-", "<task-notification", "<system", "<local-command")):
            continue
        turn_start = i

    commands: list[str] = []
    for raw in lines[turn_start:]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Bash":
                continue
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


def decide(payload: dict) -> str | None:
    """Return blocking feedback, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not claims_restart_is_safe(message):
        return None

    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    commands = bash_commands_this_turn(transcript_path) if transcript_path else []
    joined = "\n".join(commands)
    has_queue_check = bool(QUEUE_CHECK_RE.search(joined))
    has_session_check = bool(SESSION_CHECK_RE.search(joined))

    if has_queue_check and has_session_check:
        return None

    missing = []
    if not has_queue_check:
        missing.append("the workflow/task queue on that host")
    if not has_session_check:
        missing.append("concurrent logins/sessions on that host (e.g. `who`/`w`/`last`)")

    return (
        "This message asserts a remote-host restart is low-risk/safe, but this turn "
        "only shows evidence of " + str(2 - len(missing)) + " of 2 needed checks. Before "
        "finishing, also check " + " and ".join(missing) +
        " -- a single signal is not enough to call a restart safe on a shared host."
    )
