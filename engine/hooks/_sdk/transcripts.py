from __future__ import annotations

import glob
import json
import os
import re

CODEX_SESSIONS_ENV = "CATSTACK_CODEX_SESSIONS_DIR"
CODEX_HOME_ENV = "CODEX_HOME"
THREAD_ID = re.compile(r"^[0-9A-Za-z-]{8,64}$")


def codex_sessions_root() -> str:
    override = os.environ.get(CODEX_SESSIONS_ENV)
    if override:
        return override
    home = os.environ.get(CODEX_HOME_ENV) or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "sessions")


def codex_rollout(payload: dict) -> str:
    thread = payload.get("thread-id") or payload.get("thread_id")
    if not isinstance(thread, str) or not THREAD_ID.match(thread):
        return ""
    pattern = os.path.join(codex_sessions_root(), "*", "*", "*", f"rollout-*-{thread}.jsonl")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else ""


def codex_session_model(thread: str) -> str:
    """Model named in the session log. Empty when the log is missing."""
    path = codex_rollout({"thread-id": thread})
    if not path:
        return ""
    _session_id, points = codex_model_points(path)
    return points[-1][1] if points else ""


def codex_model_points(path: str) -> tuple[str, list[tuple[str, str]]]:
    """Session id and (timestamp, model) pairs from one rollout file."""
    session_id = ""
    points: list[tuple[str, str]] = []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "", []
    with handle:
        for line in handle:
            if "session_meta" not in line and "turn_context" not in line and "world_state" not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            if entry.get("type") == "session_meta":
                raw_id = payload.get("session_id") or payload.get("id") or ""
                if isinstance(raw_id, str) and raw_id:
                    session_id = raw_id
                continue
            model = _rollout_model(entry.get("type"), payload)
            stamp = entry.get("timestamp")
            if model and isinstance(stamp, str) and stamp:
                points.append((stamp, model))
    return session_id, points


def _rollout_model(kind: object, payload: dict) -> str:
    if kind == "turn_context":
        model = payload.get("model")
        return model.strip() if isinstance(model, str) else ""
    if kind == "world_state":
        state = payload.get("state")
        if isinstance(state, dict):
            model = state.get("model")
            return model.strip() if isinstance(model, str) else ""
    return ""


def subagent_transcripts(transcript: str) -> list[str]:
    if not transcript.endswith(".jsonl"):
        return []
    folder = os.path.join(transcript[: -len(".jsonl")], "subagents")
    return sorted(glob.glob(os.path.join(folder, "*.jsonl")))
