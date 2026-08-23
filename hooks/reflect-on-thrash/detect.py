"""Decide whether a transcript is thrashy enough to spawn reflect.

Uses skills/reflect/scripts/token_audit.py as the source of truth. Fail-open:
any parse/IO/import error means "no hit" so a broken hook never bricks a session.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE))
TOKEN_AUDIT_DIR = os.path.join(REPO_DIR, "skills", "reflect", "scripts")

STATE_DIR = os.environ.get(
    "REFLECT_ON_THRASH_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-reflect-on-thrash"),
)

# Cost-only flags stay out: a cheaper-model candidate is not "thrash."
# One accidental re-read is also too common to spend a reflect on.
HOOK_THRESHOLDS = {
    "recurring-failure-signatures": 1,
    "no-verify-edit-streak": 1,
    "frustration-signals": 1,
    "redundant-reads": 3,
}

ALREADY_REFLECT_RE = re.compile(r"(?i)\b/?reflect\b")
FOLLOWUP_PREFIX = (
    "Thrash flagged on this transcript ({reasons}). Read the reflect skill "
    "and spawn a subagent for steps 1-4 on this exact file: {path}. Then "
    "present Accepted / Backlog / Route-to-automate-me / Rejected and wait "
    "for approval. Do not edit skills until the user picks. Do not skip "
    "because the task also finished."
)


def _load_token_audit():
    if TOKEN_AUDIT_DIR not in sys.path:
        sys.path.insert(0, TOKEN_AUDIT_DIR)
    import token_audit  # noqa: WPS433 — runtime path to the sibling skill

    return token_audit


def sniff_mode(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            for i, line in enumerate(handle):
                if i > 40:
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or data.get("type") != "assistant":
                    continue
                message = data.get("message")
                if isinstance(message, dict) and "usage" in message:
                    return "claude"
    except OSError:
        return "cursor"
    return "cursor"


def _hits_from_flags(flags: list[dict[str, Any]]) -> list[str]:
    hits = []
    for flag in flags:
        need = HOOK_THRESHOLDS.get(flag.get("name"))
        if need is None:
            continue
        if flag.get("value") == "yes" and int(flag.get("count") or 0) >= need:
            hits.append(f"{flag['name']}={flag['count']}")
    return hits


def _cursor_duplicate_hits(path: str) -> list[str]:
    token_audit = _load_token_audit()
    counts: dict[tuple[str, str], int] = {}
    try:
        for data in token_audit.read_jsonl(path):
            message = data.get("message") if isinstance(data, dict) else None
            if not isinstance(message, dict):
                continue
            for block in message.get("content", []) or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name") or "")
                digest, _ = token_audit.sig(name, block.get("input"))
                key = (name, digest)
                counts[key] = counts.get(key, 0) + 1
    except (OSError, TypeError, ValueError):
        return []
    worst = max(counts.values(), default=0)
    if worst >= 3:
        return [f"exact-duplicate-tool-calls={worst}"]
    return []


def thrash_hits(path: str) -> list[str]:
    """Named hits for a transcript, or [] if clean / unreadable."""
    if not path or not os.path.isfile(path):
        return []
    try:
        if sniff_mode(path) == "claude":
            token_audit = _load_token_audit()
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            return _hits_from_flags(list(result.get("flags") or []))
        return _cursor_duplicate_hits(path)
    except Exception:
        return []


def marker_path(transcript_path: str) -> str:
    digest = hashlib.sha1(os.path.abspath(transcript_path).encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(transcript_path: str) -> bool:
    return os.path.isfile(marker_path(transcript_path))


def mark_prompted(transcript_path: str) -> None:
    path = marker_path(transcript_path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(transcript_path + "\n")
    except OSError:
        pass


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def user_already_asked_reflect(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_user_line(data):
                    continue
                text = _user_text(data)
                if not text or text.lstrip().startswith(
                    ("<command-", "<task-notification", "<system")
                ):
                    continue
                if ALREADY_REFLECT_RE.search(text):
                    return True
    except OSError:
        return False
    return False


def _user_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "\n".join(parts)
    return ""


def resolve_transcript(payload: dict) -> str:
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(root, project, "agent-transcripts", conv, f"{conv}.jsonl")
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    cwd = payload.get("cwd") or payload.get("workspace_roots")
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else ""
    if isinstance(cwd, str) and cwd:
        encoded = cwd.replace("/", "-").lstrip("-")
        transcripts = os.path.join(
            os.path.expanduser("~"), ".cursor", "projects", encoded, "agent-transcripts"
        )
        newest = _newest_jsonl(transcripts)
        if newest:
            return newest
    return ""


def _newest_jsonl(root: str) -> str:
    newest_path = ""
    newest_mtime = -1.0
    try:
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_path = path
    except OSError:
        return ""
    return newest_path


def decide(payload: dict) -> str | None:
    """Return the follow-up instruction, or None to stay silent."""
    if payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path:
        return None
    if already_prompted(path) or user_already_asked_reflect(path):
        return None
    hits = thrash_hits(path)
    if not hits:
        return None
    mark_prompted(path)
    return FOLLOWUP_PREFIX.format(reasons=", ".join(hits), path=path)
