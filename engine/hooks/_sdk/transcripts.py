from __future__ import annotations

import glob
import json
import os
import re
from typing import Mapping

CODEX_SESSIONS_ENV = "CATSTACK_CODEX_SESSIONS_DIR"
CODEX_HOME_ENV = "CODEX_HOME"
CLAUDE_PROJECTS_ENV = "CATSTACK_CLAUDE_PROJECTS_DIR"
THREAD_ID = re.compile(r"^[0-9A-Za-z-]{8,64}$")
SYNTHETIC = "<synthetic>"


def is_publishable_model(model: object) -> bool:
    """True when model is a non-blank identity that is not the synthetic marker."""
    if not isinstance(model, str):
        return False
    stripped = model.strip()
    return bool(stripped) and stripped != SYNTHETIC


def named_model(event: Mapping[str, object]) -> str:
    """Model named on the hook envelope. Never blank or <synthetic>."""
    for key in ("model", "model_id", "modelId", "agent_model"):
        value = event.get(key)
        if is_publishable_model(value):
            return str(value).strip()
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        for key in ("model", "model_id", "modelId"):
            value = metadata.get(key)
            if is_publishable_model(value):
                return str(value).strip()
    return ""


def session_id_from_event(event: Mapping[str, object]) -> str:
    for key in ("session_id", "sessionId", "session", "thread-id", "thread_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def cursor_peer_model(
    session_id: str,
    stamp: str,
    peers: Mapping[str, list[tuple[str, str]]],
) -> str:
    """Latest peer-named model for a Cursor session at or before stamp."""
    if not session_id:
        return ""
    points = peers.get(session_id) or []
    if not points:
        return ""
    chosen = ""
    for point_stamp, model in points:
        if not is_publishable_model(model):
            continue
        if not stamp or not point_stamp or point_stamp <= stamp:
            chosen = model.strip()
        elif chosen:
            break
    if chosen:
        return chosen
    for _point_stamp, model in points:
        if is_publishable_model(model):
            return model.strip()
    return ""


def resolve_model(
    event: Mapping[str, object],
    harness: str = "",
    peer_models: Mapping[str, list[tuple[str, str]]] | None = None,
) -> str:
    """One model resolver for live events and backfill helpers.

    Order: named envelope, Claude transcript path, Claude session log,
    Codex rollout, Cursor peer timelines. Never returns blank or <synthetic>
    as a successful identity — empty means unresolved.
    """
    named = named_model(event)
    if named:
        return named
    transcript = str(event.get("transcript_path") or event.get("transcriptPath") or "")
    from_transcript = claude_transcript_model(transcript)
    if from_transcript:
        return from_transcript
    session = session_id_from_event(event)
    if harness == "claude" or (not harness and session):
        from_session = claude_session_model(session)
        if from_session:
            return from_session
    if harness == "codex" or "thread-id" in event or "thread_id" in event:
        thread = event.get("thread-id") or event.get("thread_id") or session
        if isinstance(thread, str) and thread:
            from_codex = codex_session_model(thread)
            if from_codex:
                return from_codex
    if harness == "cursor" and peer_models is not None:
        stamp = str(event.get("ts") or event.get("timestamp") or "")
        return cursor_peer_model(session, stamp, peer_models)
    return ""


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
        return model.strip() if is_publishable_model(model) else ""
    if kind == "world_state":
        state = payload.get("state")
        if isinstance(state, dict):
            model = state.get("model")
            return model.strip() if is_publishable_model(model) else ""
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
        if is_publishable_model(model):
            return str(model).strip()
    attachment = entry.get("attachment")
    if isinstance(attachment, dict):
        identity = attachment.get("identity")
        if isinstance(identity, dict):
            model = identity.get("modelId") or identity.get("model")
            if is_publishable_model(model):
                return str(model).strip()
    return ""


def subagent_transcripts(transcript: str) -> list[str]:
    if not transcript.endswith(".jsonl"):
        return []
    folder = os.path.join(transcript[: -len(".jsonl")], "subagents")
    return sorted(glob.glob(os.path.join(folder, "*.jsonl")))
