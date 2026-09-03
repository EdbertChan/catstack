"""Session-local edit-streak state for narrow-the-scope. Fail-open."""
from __future__ import annotations

import json
import os
from typing import Any

STATE_DIR = os.environ.get(
    "CATSTACK_NARROW_THE_SCOPE_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-narrow-the-scope"),
)


def _session_key(payload: dict) -> str:
    for key in ("session_id", "sessionId", "transcript_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("/", "_")[-80:]
    return str(payload.get("cwd") or "default").replace("/", "_")[-80:]


def state_path(payload: dict) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"{_session_key(payload)}.json")


def load_state(payload: dict) -> dict[str, Any]:
    try:
        with open(state_path(payload)) as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_state(payload: dict, state: dict[str, Any]) -> None:
    try:
        with open(state_path(payload), "w") as handle:
            json.dump(state, handle)
    except OSError:
        pass
