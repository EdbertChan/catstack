"""repeat-deny-stop: the same deny twice in a row means stop calling tools.

A gate that denies a tool call is a stop signal the user put there on
purpose. Retrying through a different tool (Bash denied, so Read; Read
denied, so Skill) is getting past it. This hook keeps the last deny reason
per session. When the next tool call is denied with the identical reason,
it adds one message: stop calling tools and do what the deny text says.

It never blocks. Only identical reasons in immediate succession count: any
tool call that is not a deny, or a deny with a different reason, starts the
count over. The tool name is not part of the reason, so switching tools does
not dodge the match.

Each call has three outcomes: deny (with a reason), not a deny, or
unchecked (no result text in the payload and none in the transcript). An
unchecked call leaves the stored reason as it was and adds no message; it
is logged, never counted as clean.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from typing import Any

STATE_DIR = os.environ.get(
    "REPEAT_DENY_STOP_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-repeat-deny-stop"),
)
TTL_SECONDS = 24 * 3600
REASON_CHARS = 600

HOOK_DENY_RE = re.compile(r"\A\s*PreToolUse:[^\s:]+ hook error: (?P<reason>.+)\Z", re.S)
PERMISSION_DENY_RE = re.compile(r"\A\s*Permission to use \S+ has been denied(?P<reason>.*)\Z", re.S)
USER_REJECT_PREFIX = "The user doesn't want to proceed with this tool use."

STOP_MESSAGE = (
    "repeat-deny-stop: two tool calls in a row were denied for the same reason:\n"
    "    {reason}\n"
    "Stop calling tools. A different tool does not get past this deny; it is a stop "
    "signal the user put there on purpose. Do what the deny text says, or tell the user "
    "it blocked you and what it asks of them, then end the turn."
)

DENY = "deny"
OTHER = "other"
UNCHECKED = "unchecked"


def deny_reason(text: Any) -> str | None:
    """The deny reason in a tool result, or None when the result is not a deny."""
    if not isinstance(text, str):
        return None
    match = HOOK_DENY_RE.match(text)
    if match:
        return match.group("reason").strip()
    match = PERMISSION_DENY_RE.match(text)
    if match:
        return ("permission denied" + match.group("reason")).strip()
    if text.lstrip().startswith(USER_REJECT_PREFIX):
        return text.strip()
    return None


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def transcript_results(payload: dict[str, Any], wanted: set[str]) -> dict[str, str | None] | None:
    """tool_result by tool_use_id for the wanted ids: the text when it is an
    error, None when it is not. Returns None when the transcript cannot be read."""
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    if not isinstance(path, str) or not path:
        return None
    found: dict[str, str | None] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not any(tool_id in line for tool_id in wanted):
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message") if isinstance(data, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tool_id = block.get("tool_use_id")
                    if tool_id in wanted:
                        found[tool_id] = _result_text(block.get("content")) if block.get("is_error") else None
    except OSError:
        return None
    return found


def classify_calls(payload: dict[str, Any]) -> list[tuple[str, str | None]]:
    """One (outcome, reason) per tool call in the batch, in order."""
    calls = [c for c in payload.get("tool_calls") or [] if isinstance(c, dict)]
    missing = {
        str(c.get("tool_use_id"))
        for c in calls
        if "tool_response" not in c and c.get("tool_use_id")
    }
    from_transcript = transcript_results(payload, missing) if missing else {}
    outcomes: list[tuple[str, str | None]] = []
    for call in calls:
        if "tool_response" in call:
            text = call.get("tool_response")
        else:
            tool_id = call.get("tool_use_id")
            if from_transcript is None or tool_id not in from_transcript:
                outcomes.append((UNCHECKED, None))
                continue
            text = from_transcript[tool_id]
        reason = deny_reason(text)
        outcomes.append((DENY, reason) if reason else (OTHER, None))
    return outcomes


def _session_identity(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip()}"
    return ""


def state_path(payload: dict[str, Any]) -> str:
    identity = _session_identity(payload)
    if not identity:
        return ""
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return os.path.join(STATE_DIR, f"{digest}.json")


def load_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = state_path(payload)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    if time.time() - float(value.get("updated_at") or 0) > TTL_SECONDS:
        return {}
    return value


def save_state(payload: dict[str, Any], state: dict[str, Any]) -> None:
    path = state_path(payload)
    if not path:
        return
    state["updated_at"] = time.time()
    temp_path = ""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="repeat-deny-stop-", dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    except OSError:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def record_batch(payload: dict[str, Any]) -> tuple[str | None, int]:
    """Fold one PostToolBatch into the session state.

    Returns (stop message or None, number of unchecked calls)."""
    if not state_path(payload):
        return None, 0
    state = load_state(payload)
    last = state.get("last_deny")
    message = None
    unchecked = 0
    for outcome, reason in classify_calls(payload):
        if outcome == UNCHECKED:
            unchecked += 1
            continue
        if outcome == OTHER:
            last = None
            continue
        if reason == last:
            message = STOP_MESSAGE.format(reason=reason[:REASON_CHARS])
        last = reason
    state["last_deny"] = last
    save_state(payload, state)
    return message, unchecked
