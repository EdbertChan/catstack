"""Stop a document rewrite that fails the technical-writing sentence checks.

Fires only when the user asked for a document. A chat reply stays silent.
A missing user prompt fails open. An unreadable reply is unchecked.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_sdk"))
from finding import Finding  # noqa: E402
from source_repo import source_repo  # noqa: E402

RULE_HIT = "technical-writing-guard.sentence"
RULE_UNCHECKED = "technical-writing-guard.unchecked"
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_RE = re.compile(r"`[^`\n]+`")
USER_KEYS = ("user_prompt", "prompt", "user_message")
REPLY_KEYS = (
    "last_assistant_message",
    "last-assistant-message",
    "lastAssistantMessage",
    "assistant_message",
    "response",
)


SKILL_SCRIPTS = Path("product") / "skills" / "technical-writing" / "scripts"
INSTALLED_SKILL_ROOTS = (
    Path("~/.claude/skills"), Path("~/.cursor/skills"), Path("~/.codex/skills"), Path("~/workspace/skills"),
)


def grader_script_dirs() -> list[Path]:
    """The folders that may hold grade_prose.py: the checkout named by the install record, the checkout this file sits in, then each harness's installed skill link."""
    recorded = source_repo(__file__)
    recorded_dirs = [Path(recorded) / SKILL_SCRIPTS] if recorded else []
    repo_relative = Path(__file__).resolve().parents[3] / SKILL_SCRIPTS
    installed = [root.expanduser() / "technical-writing" / "scripts" for root in INSTALLED_SKILL_ROOTS]
    return [*recorded_dirs, repo_relative, *installed]


def _grader():
    tried = grader_script_dirs()
    for script_dir in tried:
        if not (script_dir / "grade_prose.py").is_file():
            continue
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        import grade_prose

        return grade_prose
    raise ImportError("grade_prose.py is in none of: " + ", ".join(str(d) for d in tried))


def visible_prose(text: str) -> str:
    return INLINE_RE.sub(" ", FENCE_RE.sub(" ", text))


def user_text(event: dict) -> str | None:
    for key in USER_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _blocks_text(message: object) -> str:
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            if block["text"].strip():
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _row_text(entry: dict) -> str:
    message = entry.get("message")
    text = _blocks_text(message) if message is not None else ""
    if text:
        return text
    return _blocks_text(entry)


def _transcript_texts(path: str) -> tuple[str, str]:
    last_user = ""
    last_assistant = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                role = entry.get("role") or entry.get("type")
                text = _row_text(entry)
                if not text:
                    continue
                if role == "user":
                    last_user = text
                elif role == "assistant":
                    last_assistant = text
    except (OSError, UnicodeError):
        return "", ""
    return last_user, last_assistant


def _input_messages(event: dict) -> str:
    messages = event.get("input-messages")
    if not isinstance(messages, list):
        return ""
    last = ""
    for item in messages:
        if isinstance(item, str) and item.strip():
            last = item.strip()
    return last


def enrich(event: dict) -> dict:
    out = dict(event)
    if user_text(out) is None:
        asked = _input_messages(out)
        path = out.get("transcript_path") or out.get("transcriptPath")
        transcript_user, transcript_reply = ("", "")
        if isinstance(path, str) and path.strip():
            transcript_user, transcript_reply = _transcript_texts(path)
            out["_transcript_reply"] = transcript_reply
        if asked:
            out["user_prompt"] = asked
        elif transcript_user:
            out["user_prompt"] = transcript_user
    reply = ""
    for key in REPLY_KEYS:
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            reply = value
            break
    if not reply:
        reply = out.get("_transcript_reply") or ""
        if not reply:
            path = out.get("transcript_path") or out.get("transcriptPath")
            if isinstance(path, str) and path.strip():
                _user, reply = _transcript_texts(path)
    if reply:
        out["last_assistant_message"] = reply
    return out


def detect(event: dict) -> list[Finding]:
    if not isinstance(event, dict):
        return []
    if event.get("stop_hook_active"):
        return []
    enriched = enrich(event)
    asked = user_text(enriched)
    if asked is None:
        return []
    try:
        grader = _grader()
    except ImportError as error:
        return [
            Finding(
                rule_id=RULE_UNCHECKED,
                subject="technical writing grader",
                message="The document check could not load. Leave the reply unchecked.",
                evidence=f"grade_prose import failed: {error}",
            )
        ]
    event = enriched
    if not grader.applies_to(asked):
        return []
    message = event.get("last_assistant_message")
    if not isinstance(message, str):
        return [
            Finding(
                rule_id=RULE_UNCHECKED,
                subject="document reply",
                message="The document reply could not be read. Leave it unchecked.",
                evidence="last_assistant_message missing",
            )
        ]
    hits = grader.sentence_findings(visible_prose(message))
    return [
        Finding(
            rule_id=RULE_HIT,
            subject="document sentence",
            message=hit,
            evidence=hit,
        )
        for hit in hits
    ]
