"""Session-local state for empty-Grep / repeat-Grep leak detection.

Fail-open: any IO/parse error is ignored by callers.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

STATE_DIR = os.environ.get(
    "BUG_COMPLAINT_LEAK_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "bug-complaint-leak"),
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
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_state(payload: dict, state: dict[str, Any]) -> None:
    path = state_path(payload)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def remember_bug_complaint(payload: dict, prompt: str, quotes: list[str], checklist: str) -> None:
    state = load_state(payload)
    state["bug_complaint"] = {
        "at": time.time(),
        "quotes": quotes,
        "checklist": checklist,
        "prompt_preview": prompt[:400],
    }
    state["empty_greps"] = []
    state["last_grep_sig"] = None
    state["cursor_checklist_pending"] = True
    save_state(payload, state)


def record_empty_grep(payload: dict, pattern: str, path: str | None, glob: str | None) -> None:
    state = load_state(payload)
    empty = list(state.get("empty_greps") or [])
    empty.append(
        {
            "at": time.time(),
            "pattern": pattern,
            "path": path or "",
            "glob": glob or "",
        }
    )
    state["empty_greps"] = empty[-8:]
    save_state(payload, state)


def clear_empty_greps(payload: dict) -> None:
    state = load_state(payload)
    state["empty_greps"] = []
    save_state(payload, state)


def note_git_history_lookup(payload: dict) -> None:
    """Shell ran git grep origin/master or git log -S — clears empty-grep streak."""
    clear_empty_greps(payload)
    state = load_state(payload)
    state["did_origin_lookup"] = True
    save_state(payload, state)


def note_edit(payload: dict) -> None:
    state = load_state(payload)
    state["last_grep_sig"] = None
    save_state(payload, state)


def grep_signature(pattern: str, path: str | None, glob: str | None) -> str:
    return json.dumps({"pattern": pattern, "path": path or "", "glob": glob or ""}, sort_keys=True)


def consecutive_empty_for_quote(state: dict, quotes: list[str]) -> int:
    empty = list(state.get("empty_greps") or [])
    if not empty or not quotes:
        return 0
    count = 0
    for entry in reversed(empty):
        pattern = str(entry.get("pattern") or "")
        if any(q.lower() in pattern.lower() or pattern.lower() in q.lower() for q in quotes):
            count += 1
        else:
            break
    return count
