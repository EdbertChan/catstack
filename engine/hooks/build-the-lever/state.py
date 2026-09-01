"""Session-local state for build-the-lever inject hooks.

Fail-open: callers ignore IO/parse errors.
"""
from __future__ import annotations

import json
import os
from typing import Any

STATE_DIR = os.environ.get(
    "CATSTACK_BUILD_THE_LEVER_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-build-the-lever"),
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
    path = state_path(payload)
    try:
        with open(path) as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_state(payload: dict, state: dict[str, Any]) -> None:
    path = state_path(payload)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            json.dump(state, handle)
    except OSError:
        pass
