from __future__ import annotations

import glob
import json
import os
import re

CODEX_SESSIONS_ENV = "CATSTACK_CODEX_SESSIONS_DIR"
CODEX_HOME_ENV = "CODEX_HOME"
CLAUDE_PROJECTS_ENV = "CATSTACK_CLAUDE_PROJECTS_DIR"
THREAD_ID = re.compile(r"^[0-9A-Za-z-]{8,64}$")
SYNTHETIC = "<synthetic>"


def codex_sessions_root() -> str:
    override = os.environ.get(CODEX_SESSIONS_ENV)
    if override:
        return override
    home = os.environ.get(CODEX_HOME_ENV) or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "sessions")


def claude_projects_root() -> str:
    override = os.environ.get(CLAUDE_PROJECTS_ENV)
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


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

def claude_transcript_for_session(session_id: str) -> str:
    """Newest Claude transcript path for a session id. Empty when missing."""
    if not isinstance(session_id, str) or not THREAD_ID.match(session_id):
        return ""
    pattern = os.path.join(claude_projects_root(), "*", f"{session_id}.jsonl")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else ""


def claude_session_model(session_id: str) -> str:
    """Model named in the Claude transcript for a session. Empty when missing."""
    path = claude_transcript_for_session(session_id)
    if not path:
        return ""
    _sid, points = claude_model_points(path)
    return points[-1][1] if points else ""


def claude_transcript_model(path: str) -> str:
    """Latest assistant model in a Claude transcript. Empty when missing."""
    _sid, points = claude_model_points(path)
    return points[-1][1] if points else ""


def claude_model_points(path: str) -> tuple[str, list[tuple[str, str]]]:
    """Session id and (timestamp, model) pairs from one Claude transcript."""
    if not path or not path.endswith(".jsonl") or not os.path.isfile(path):
        return "", []
    session_id = os.path.splitext(os.path.basename(path))[0]
    points: list[tuple[str, str]] = []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "", []
    with handle:
        for line in handle:
            if "model" not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            model = _claude_entry_model(entry)
            stamp = entry.get("timestamp")
            if model and isinstance(stamp, str) and stamp:
                points.append((stamp, model))
            elif model and not points:
                points.append(("", model))
    return session_id, points


def _claude_entry_model(entry: dict) -> str:
    message = entry.get("message")
    if isinstance(message, dict):
        model = message.get("model")
        if isinstance(model, str):
            stripped = model.strip()
            if stripped and stripped != SYNTHETIC:
                return stripped
    attachment = entry.get("attachment")
    if isinstance(attachment, dict):
        identity = attachment.get("identity")
        if isinstance(identity, dict):
            model = identity.get("modelId") or identity.get("model")
            if isinstance(model, str):
                stripped = model.strip()
                if stripped and stripped != SYNTHETIC:
                    return stripped
    return ""


def subagent_transcripts(transcript: str) -> list[str]:
    if not transcript.endswith(".jsonl"):
        return []
    folder = os.path.join(transcript[: -len(".jsonl")], "subagents")
    return sorted(glob.glob(os.path.join(folder, "*.jsonl")))
