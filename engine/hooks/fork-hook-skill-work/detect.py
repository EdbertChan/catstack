"""fork-hook-skill-work: hook and skill edits belong in their own XIRP session.

Exploring, fixing or proving a hook or a skill swamps the session the user is
steering: hook blocks, log mining and a PR flow pile onto unrelated work. XIRP
sets CHIRP_SESSION_ID and CHIRP_PROJECT_ID inside every session it manages, so a
session without both is one the user is working in directly. When such a session
edits a hook or skill path, nudge once per session toward `xirp session new` with
a self-contained brief. Warn only: a denied tool call can be final in a
listening session. Fails open on any error.
"""
from __future__ import annotations

import os
import re
import sys

try:
    from finding import Finding
except ImportError:
    from pathlib import Path

    SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
    sys.path.insert(0, str(SDK_DIR))
    from finding import Finding

EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
WATCHED_RE = re.compile(
    r"(?:^|/)(?:engine/hooks|(?:engine|corpus|product)/skills|\.claude/hooks|\.claude/skills)/"
)
STATE_DIR_ENV = "CATSTACK_FORK_NUDGE_STATE_DIR"
RULE_NOT_FORKED = "fork-hook-skill-work.not-in-managed-session"

MESSAGE = (
    "fork-hook-skill-work: {path} is a hook or skill path and this is not a managed XIRP session. "
    "Fork the work so this session keeps going: xirp session new --goal \"<self-contained brief>\" "
    "--new-branch <name> (fork-hook-skill-work)."
)


def managed_session(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("CHIRP_SESSION_ID")) and bool(env.get("CHIRP_PROJECT_ID"))


def watched_path(path: str) -> bool:
    return bool(WATCHED_RE.search(os.path.abspath(os.path.expanduser(path)).replace(os.sep, "/")))


def _state_dir() -> str:
    return os.environ.get(STATE_DIR_ENV) or os.path.expanduser("~/.cache/catstack-fork-hook-skill-work")


def already_nudged(session_id: str) -> bool:
    return os.path.exists(os.path.join(_state_dir(), re.sub(r"[^\w.-]", "_", session_id)))


def mark_nudged(session_id: str) -> None:
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(os.path.join(_state_dir(), re.sub(r"[^\w.-]", "_", session_id)), "w", encoding="utf-8"):
            pass
    except OSError as exc:
        print(f"fork-hook-skill-work: could not record the nudge: {exc}", file=sys.stderr)


def detect(event: dict[str, object]) -> list[Finding]:
    if event.get("tool_name") not in EDIT_TOOLS or managed_session():
        return []
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    path = next((tool_input[k] for k in ("file_path", "path", "notebook_path") if isinstance(tool_input.get(k), str)), None)
    if not path or not watched_path(path):
        return []
    session_id = str(event.get("session_id") or event.get("sessionId") or "unknown")
    if already_nudged(session_id):
        return []
    mark_nudged(session_id)
    message = MESSAGE.format(path=path)
    return [Finding(rule_id=RULE_NOT_FORKED, subject=path, message=message, evidence=message)]
