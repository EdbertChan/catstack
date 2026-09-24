from __future__ import annotations

import glob
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


def subagent_transcripts(transcript: str) -> list[str]:
    if not transcript.endswith(".jsonl"):
        return []
    folder = os.path.join(transcript[: -len(".jsonl")], "subagents")
    return sorted(glob.glob(os.path.join(folder, "*.jsonl")))
