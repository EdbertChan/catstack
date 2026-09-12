"""Session-local state for split-scope Cursor delivery."""
from __future__ import annotations

import json
import os
import time
from typing import Any

STATE_DIR = os.environ.get(
    "CATSTACK_SPLIT_SCOPE_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-split-scope"),
)
STATE_TTL_SECONDS = 7200


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
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {}
        updated_at = data.get("updated_at")
        now = time.time()
        if not isinstance(updated_at, (int, float)):
            return {}
        if updated_at > now + 60:
            return {}
        if now - updated_at > STATE_TTL_SECONDS:
            return {}
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_state(payload: dict, state: dict[str, Any]) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        state["updated_at"] = time.time()
        with open(state_path(payload), "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError:
        return
