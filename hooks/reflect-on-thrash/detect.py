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
# intervention-must-automate already means the class repeated — threshold 1.
HOOK_THRESHOLDS = {
    "recurring-failure-signatures": 1,
    "no-verify-edit-streak": 1,
    "frustration-signals": 1,
    "redundant-reads": 3,
    "intervention-must-automate": 1,
}

ALREADY_REFLECT_RE = re.compile(r"(?i)\b/?reflect\b|\b/?automate-me\b|\bautomate me\b")
FOLLOWUP_PREFIX = (
    "Thrash flagged on this transcript ({reasons}). Read the reflect skill "
    "and spawn a subagent for steps 1-4 on this exact file: {path}. Then "
    "present Accepted / Backlog / Route-to-automate-me / Rejected and wait "
    "for approval. Do not edit skills until the user picks. Do not skip "
    "because the task also finished."
)
INTERVENTION_FOLLOWUP = (
    "Intervention flagged on this transcript ({reasons}). This is a FAILURE, "
    "not a preference ping: the user had to restate a named constraint. "
    "Read the reflect skill AND the automate-me skill. Spawn a subagent for "
    "reflect steps 1-4 on this exact file: {path}. First offered action is "
    "automate-me (same-type complaint / forced iteration). Present Accepted / "
    "Backlog / Route-to-automate-me / Rejected and wait for approval on skill "
    "edits; invoke automate-me in the same turn. Do not skip because the task "
    "also finished."
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


def _state_file(transcript_path: str, suffix: str) -> str:
    digest = hashlib.sha1(os.path.abspath(transcript_path).encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.{suffix}")


def marker_path(transcript_path: str) -> str:
    return _state_file(transcript_path, "prompted")


def deferred_path(transcript_path: str) -> str:
    return _state_file(transcript_path, "deferred")


def already_prompted(transcript_path: str) -> bool:
    return os.path.isfile(marker_path(transcript_path))


def has_deferred(transcript_path: str) -> bool:
    return os.path.isfile(deferred_path(transcript_path))


def _touch(path: str, transcript_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(transcript_path + "\n")
    except OSError:
        pass


def mark_prompted(transcript_path: str) -> None:
    _touch(marker_path(transcript_path), transcript_path)
    try:
        os.remove(deferred_path(transcript_path))
    except OSError:
        pass


def mark_deferred(transcript_path: str) -> None:
    if already_prompted(transcript_path):
        return
    _touch(deferred_path(transcript_path), transcript_path)


def wants_interrupt(payload: dict, argv: list[str] | None = None) -> bool:
    """True only when the session is over. Mid-turn stop must stay silent."""

    args = [str(item).lower() for item in (argv if argv is not None else sys.argv[1:])]
    if any(item in {"sessionend", "session_end"} for item in args):
        return True
    event = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or payload.get("event")
        or payload.get("type")
        or ""
    ).lower()
    return event in {"sessionend", "session_end"}


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


def intervention_hit(hits: list[str]) -> bool:
    return any(str(h).startswith("intervention-must-automate") for h in hits)


def _followup(hits: list[str], path: str) -> str:
    template = INTERVENTION_FOLLOWUP if intervention_hit(hits) else FOLLOWUP_PREFIX
    return template.format(reasons=", ".join(hits), path=path)


def decide(
    payload: dict,
    *,
    argv: list[str] | None = None,
    deliver: bool | None = None,
) -> str | None:
    """Return the follow-up instruction, or None to stay silent.

    Mid-session stop/Stop records a deferred marker and returns None for
    ordinary thrash so the current task is not stolen. Delivery happens on
    sessionEnd. Same-type user intervention (`intervention-must-automate`)
    is the exception: deliver immediately (Claude Stop exit 2 / Cursor
    followup) — do not wait for session end or for the user to re-prompt.
    """
    if payload.get("stop_hook_active"):
        return None
    path = resolve_transcript(payload)
    if not path:
        return None
    if already_prompted(path) or user_already_asked_reflect(path):
        return None
    hits = thrash_hits(path)
    if not hits and not has_deferred(path):
        return None
    force_now = intervention_hit(hits)
    should_deliver = wants_interrupt(payload, argv) if deliver is None else deliver
    if force_now:
        should_deliver = True
    if not should_deliver:
        if hits:
            mark_deferred(path)
        return None
    if not hits:
        hits = ["deferred"]
    mark_prompted(path)
    return _followup(hits, path)
