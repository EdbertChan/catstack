"""Session-scoped counters the repeat hooks keep and an enforcement policy can name.

Two counters live here. ``same_error_count`` is how many times one error
signature has been recorded in a session; ``repeat_deny_count`` is how many
tool calls in a row were denied for the same reason. Both are stored the way
repeat-error-stop has always stored them: one JSON file per session under the
hook's own state directory, dropped after a day.

Each reader has three outcomes, not two: a count, zero, and no state at all.
An unreadable or expired state file reads as no state, which is reported as
zero counts here and must not be read as "the counter was checked and is low".
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

TTL_SECONDS = 24 * 3600
MAX_COMMANDS = 20
SAME_ERROR_COUNT = "same_error_count"
REPEAT_DENY_COUNT = "repeat_deny_count"
COUNTER_NAMES = (SAME_ERROR_COUNT, REPEAT_DENY_COUNT)
ERROR_STATE_DIR_ENV = "REPEAT_ERROR_STOP_STATE_DIR"
DENY_STATE_DIR_ENV = "REPEAT_DENY_STOP_STATE_DIR"
DEFAULT_ERROR_STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "catstack-repeat-error-stop")
DEFAULT_DENY_STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "catstack-repeat-deny-stop")


def state_int(value: Any, default: int = 0) -> int:
    """One stored counter as an integer, falling back when it is missing or malformed."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def session_key(payload: dict[str, Any]) -> str:
    """The session this payload belongs to, as a file-name-safe key."""
    agent_id = ""
    for key in ("agent_id", "agentId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            agent_id = ":" + value.strip()
            break
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "transcript_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return (value.strip() + agent_id).replace("/", "_")[-80:]
    cwd = payload.get("cwd") or payload.get("workspace_roots") or "default"
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else "default"
    return (str(cwd) + agent_id).replace("/", "_")[-80:]


def session_identity(payload: dict[str, Any]) -> str:
    """The session this payload names outright, or an empty string when it names none."""
    for key in ("session_id", "sessionId", "transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip()}"
    return ""


def state_path(state_dir: str, payload: dict[str, Any]) -> str:
    """The error-counter state file for this session, creating the directory."""
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, f"{session_key(payload)}.json")


def deny_state_path(state_dir: str, payload: dict[str, Any]) -> str:
    """The deny-counter state file for this session, empty when the payload names no session."""
    identity = session_identity(payload)
    if not identity:
        return ""
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return os.path.join(state_dir, f"{digest}.json")


def read_state(path: str) -> dict[str, Any]:
    """The session state at this path, or an empty state when it is missing, unreadable or expired."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if time.time() - _updated_at(data) > TTL_SECONDS:
        return {}
    return data


def _updated_at(state: dict[str, Any]) -> float:
    """When this state was last written, zero when the stamp is missing or malformed."""
    try:
        return float(state.get("updated_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def load_state(state_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The error-counter state for this session."""
    try:
        path = state_path(state_dir, payload)
    except OSError:
        return {}
    return read_state(path)


def load_deny_state(state_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The deny-counter state for this session."""
    return read_state(deny_state_path(state_dir, payload))


def save_state(state_dir: str, payload: dict[str, Any], state: dict[str, Any]) -> None:
    """Write the error-counter state for this session, stamped with the time."""
    state["updated_at"] = time.time()
    try:
        path = state_path(state_dir, payload)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError:
        pass


def reset_state(state_dir: str, payload: dict[str, Any]) -> None:
    """Drop the error-counter state for this session."""
    try:
        os.remove(state_path(state_dir, payload))
    except OSError:
        pass


def count_same_error(
    state: dict[str, Any],
    digest: str,
    sample: str,
    command: str = "",
    reset_on_edit: bool = True,
) -> dict[str, Any]:
    """Fold one occurrence of an error signature into the session state and return its entry."""
    errors = state.get("errors")
    if not isinstance(errors, dict):
        errors = {}
        state["errors"] = errors
    raw_entry = errors.get(digest)
    entry = raw_entry if isinstance(raw_entry, dict) else {
        "count": 0,
        "sample": sample,
        "commands": [],
        "first_at": time.time(),
        "epochs": [],
        "nudged": False,
    }
    epoch = state_int(state.get("edit_epoch"), 0)
    if reset_on_edit and entry.get("epoch", epoch) != epoch:
        entry["count"] = 0
        entry["commands"] = []
    entry["epoch"] = epoch
    epochs = entry.get("epochs")
    if not isinstance(epochs, list):
        epochs = []
    if epoch not in epochs:
        epochs.append(epoch)
    entry["epochs"] = epochs
    entry["nudged"] = bool(entry.get("nudged", False))
    commands = entry.get("commands")
    if not isinstance(commands, list):
        commands = []
    entry["commands"] = commands
    entry["count"] = state_int(entry.get("count"), 0) + 1
    entry["last_at"] = time.time()
    if command and command not in entry["commands"]:
        entry["commands"] = (entry["commands"] + [command])[-MAX_COMMANDS:]
    errors[digest] = entry
    return entry


def same_error_count(state: dict[str, Any], digest: str = "") -> int:
    """Times one error signature was recorded this session, or the highest count when no signature is named."""
    errors = state.get("errors")
    if not isinstance(errors, dict):
        return 0
    if digest:
        entry = errors.get(digest)
        return state_int(entry.get("count")) if isinstance(entry, dict) else 0
    counts = [state_int(entry.get("count")) for entry in errors.values() if isinstance(entry, dict)]
    return max(counts, default=0)


def count_repeat_deny(state: dict[str, Any], reason: str) -> int:
    """Fold one denied tool call into the session state and return the run length for its reason."""
    if state.get("last_deny") == reason:
        run_length = state_int(state.get("deny_streak"), 1) + 1
    else:
        run_length = 1
    state["last_deny"] = reason
    state["deny_streak"] = run_length
    return run_length


def clear_repeat_deny(state: dict[str, Any]) -> None:
    """A tool call that was not denied ends the current run of denies."""
    state["last_deny"] = None
    state["deny_streak"] = 0


def repeat_deny_count(state: dict[str, Any], reason: str = "") -> int:
    """Tool calls denied in a row this session, zero when the named reason is not the current run."""
    if reason and state.get("last_deny") != reason:
        return 0
    if state.get("last_deny") is None:
        return 0
    return state_int(state.get("deny_streak"))


def error_state_dir() -> str:
    """Where repeat-error-stop keeps its session state on this machine."""
    return os.environ.get(ERROR_STATE_DIR_ENV) or DEFAULT_ERROR_STATE_DIR


def deny_state_dir() -> str:
    """Where repeat-deny-stop keeps its session state on this machine."""
    return os.environ.get(DENY_STATE_DIR_ENV) or DEFAULT_DENY_STATE_DIR


def session_counters(payload: dict[str, Any]) -> dict[str, int]:
    """Every shared counter for this session, by the name an enforcement policy uses."""
    return {
        SAME_ERROR_COUNT: same_error_count(read_state(_error_state_path(payload))),
        REPEAT_DENY_COUNT: repeat_deny_count(load_deny_state(deny_state_dir(), payload)),
    }


def _error_state_path(payload: dict[str, Any]) -> str:
    """The error-counter state file for this session, without creating the directory."""
    return os.path.join(error_state_dir(), f"{session_key(payload)}.json")
