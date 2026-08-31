#!/usr/bin/env python3
"""Typed role-user transcript adapter with structural provenance.

Claude, Codex, and Cursor all serialize machine injections with a user-shaped
role. This module keeps those rows observable while making the only automation
eligible state explicit: ``provenance == "direct_human"``.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

Harness = Literal["claude", "codex", "cursor"]
Provenance = Literal["direct_human", "system", "hook", "subagent", "unknown"]


@dataclass(frozen=True)
class HumanUtterance:
    harness: Harness
    lineage_id: str
    session_id: str
    timestamp: str | None
    text: str
    provenance: Provenance
    index: int
    path: str

    @property
    def can_trigger_intervention(self) -> bool:
        return self.provenance == "direct_human"

    @property
    def event_key(self) -> tuple[str, str, str | None, str]:
        """Stable identity for copies of one utterance inside a lineage."""
        return (self.harness, self.lineage_id, self.timestamp, self.text)


CLAUDE_SYSTEM_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
)
CODEX_SYSTEM_PREFIXES = ("<environment_context>", "# AGENTS.md instructions")
CURSOR_SYSTEM_PREFIXES = (
    "<available_subagent_types>",
    "<cursor_commands>",
    "<dynamic_tools>",
    "<manually_attached_skills>",
    "<mcp_meta_tools>",
    "<mcp_server_catalog>",
    "<uploaded_documents>",
)

_CURSOR_QUERY_RE = re.compile(
    r"^<timestamp>(?P<timestamp>.*?)</timestamp>\s*"
    r"<user_query>(?P<text>.*)</user_query>\s*$",
    re.DOTALL,
)

_CLAUDE_DIRECT_ROW_KEYS = frozenset({"type", "sessionId", "timestamp", "message"})
_CLAUDE_DIRECT_MESSAGE_KEYS = frozenset({"role", "content"})
_CODEX_DIRECT_ROW_KEYS = frozenset({"type", "timestamp", "payload"})
_CODEX_DIRECT_PAYLOAD_KEYS = frozenset({
    "type",
    "role",
    "content",
    "internal_chat_message_metadata_passthrough",
})
_CODEX_DIRECT_METADATA_KEYS = frozenset({"content_item_kinds"})
_CURSOR_DIRECT_ROW_KEYS = frozenset({"role", "timestamp", "message"})
_CURSOR_DIRECT_MESSAGE_KEYS = frozenset({"role", "content"})
_TEXT_BLOCK_KEYS = frozenset({"type", "text"})


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _has_only_keys(value: dict[str, Any], allowed: frozenset[str]) -> bool:
    return not set(value).difference(allowed)


def _is_text_block_list(content: Any, block_type: str) -> bool:
    return (
        isinstance(content, list)
        and bool(content)
        and all(
            isinstance(block, dict)
            and _has_only_keys(block, _TEXT_BLOCK_KEYS)
            and block.get("type") == block_type
            and isinstance(block.get("text"), str)
            for block in content
        )
    )


def _is_direct_claude_row(row: dict[str, Any], message: Any) -> bool:
    return (
        isinstance(message, dict)
        and _has_only_keys(row, _CLAUDE_DIRECT_ROW_KEYS)
        and _has_only_keys(message, _CLAUDE_DIRECT_MESSAGE_KEYS)
        and message.get("role") == "user"
        and isinstance(message.get("content"), (str, list))
    )


def _is_direct_codex_row(
    row: dict[str, Any], payload: dict[str, Any], metadata: dict[str, Any]
) -> bool:
    kinds = metadata.get("content_item_kinds")
    return (
        row.get("type") == "response_item"
        and _has_only_keys(row, _CODEX_DIRECT_ROW_KEYS)
        and _has_only_keys(payload, _CODEX_DIRECT_PAYLOAD_KEYS)
        and _has_only_keys(metadata, _CODEX_DIRECT_METADATA_KEYS)
        and isinstance(kinds, list)
        and bool(kinds)
        and all(kind == "user.text" for kind in kinds)
        and _is_text_block_list(payload.get("content"), "input_text")
    )


def _is_direct_cursor_row(row: dict[str, Any], message: dict[str, Any]) -> bool:
    return (
        _has_only_keys(row, _CURSOR_DIRECT_ROW_KEYS)
        and _has_only_keys(message, _CURSOR_DIRECT_MESSAGE_KEYS)
        and _is_text_block_list(message.get("content"), "text")
    )


def _path_identity(path: str) -> tuple[str, str, bool]:
    normalized = path.replace("\\", "/")
    stem = os.path.splitext(os.path.basename(path))[0]
    if "/subagents/" not in normalized:
        return stem, stem, False
    parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return parent or stem, stem, True


def _claude_utterances(path: str, rows: list[dict[str, Any]]) -> list[HumanUtterance]:
    path_lineage, path_session, path_is_subagent = _path_identity(path)
    out: list[HumanUtterance] = []
    for index, row in enumerate(rows):
        if row.get("type") != "user":
            continue
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            continue
        text = _text_from_content(content).strip()
        if not text:
            continue
        lineage = str(row.get("sessionId") or path_lineage)
        is_subagent = path_is_subagent or bool(row.get("agentId"))
        session = str(row.get("agentId") or (path_session if is_subagent else lineage))
        if is_subagent:
            provenance: Provenance = "subagent"
        elif row.get("isMeta") or "[Request interrupted by user" in text:
            provenance = "hook"
        elif text.lstrip().startswith(CLAUDE_SYSTEM_PREFIXES):
            provenance = "system"
        elif _is_direct_claude_row(row, message):
            provenance = "direct_human"
        else:
            provenance = "unknown"
        out.append(HumanUtterance(
            harness="claude",
            lineage_id=lineage,
            session_id=session,
            timestamp=row.get("timestamp"),
            text=text,
            provenance=provenance,
            index=index,
            path=path,
        ))
    return out


def _codex_identity(path: str, rows: list[dict[str, Any]]) -> tuple[str, str, bool]:
    path_lineage, path_session, path_is_subagent = _path_identity(path)
    own_meta = next((row.get("payload") for row in rows if row.get("type") == "session_meta"), {})
    if not isinstance(own_meta, dict):
        own_meta = {}
    session = str(own_meta.get("id") or path_session)
    lineage = str(
        own_meta.get("session_id")
        or own_meta.get("parent_thread_id")
        or own_meta.get("forked_from_id")
        or session
        or path_lineage
    )
    is_subagent = path_is_subagent or own_meta.get("thread_source") == "subagent"
    return lineage, session, is_subagent


def _codex_utterances(path: str, rows: list[dict[str, Any]]) -> list[HumanUtterance]:
    lineage, session, is_subagent = _codex_identity(path, rows)
    out: list[HumanUtterance] = []
    for index, row in enumerate(rows):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        text = ""
        metadata: dict[str, Any] = {}
        if row.get("type") == "response_item" and payload.get("type") == "message":
            if payload.get("role") != "user":
                continue
            text = _text_from_content(payload.get("content")).strip()
            raw_metadata = payload.get("internal_chat_message_metadata_passthrough")
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
        elif row.get("type") == "event_msg" and payload.get("type") == "user_message":
            text = _text_from_content(payload.get("message") or payload.get("text")).strip()
        else:
            continue
        if not text:
            continue
        kinds = metadata.get("content_item_kinds") or []
        if is_subagent:
            provenance: Provenance = "subagent"
        elif any("hook" in str(kind) for kind in kinds):
            provenance = "hook"
        elif kinds and not all(str(kind).startswith("user.") for kind in kinds):
            provenance = "system"
        elif text.lstrip().startswith(CODEX_SYSTEM_PREFIXES):
            provenance = "system"
        elif _is_direct_codex_row(row, payload, metadata):
            provenance = "direct_human"
        else:
            provenance = "unknown"
        out.append(HumanUtterance(
            harness="codex",
            lineage_id=lineage,
            session_id=session,
            timestamp=row.get("timestamp"),
            text=text,
            provenance=provenance,
            index=index,
            path=path,
        ))
    return out


def _cursor_utterances(path: str, rows: list[dict[str, Any]]) -> list[HumanUtterance]:
    lineage, session, is_subagent = _path_identity(path)
    out: list[HumanUtterance] = []
    for index, row in enumerate(rows):
        message = row.get("message")
        role = row.get("role") or (message.get("role") if isinstance(message, dict) else None)
        if role != "user" or not isinstance(message, dict):
            continue
        raw_text = _text_from_content(message.get("content")).strip()
        if not raw_text:
            continue
        timestamp = row.get("timestamp")
        match = _CURSOR_QUERY_RE.match(raw_text)
        text = match.group("text").strip() if match else raw_text
        if match and not timestamp:
            timestamp = match.group("timestamp").strip()
        if is_subagent:
            provenance: Provenance = "subagent"
        elif raw_text.lstrip().startswith(CURSOR_SYSTEM_PREFIXES):
            provenance = "system"
        elif match and _is_direct_cursor_row(row, message):
            provenance = "direct_human"
        else:
            provenance = "unknown"
        out.append(HumanUtterance(
            harness="cursor",
            lineage_id=lineage,
            session_id=session,
            timestamp=timestamp,
            text=text,
            provenance=provenance,
            index=index,
            path=path,
        ))
    return out


def extract_utterances(path: str, harness: Harness) -> list[HumanUtterance]:
    rows = _read_jsonl(path)
    if harness == "claude":
        return _claude_utterances(path, rows)
    if harness == "codex":
        return _codex_utterances(path, rows)
    return _cursor_utterances(path, rows)


def direct_human_utterances(path: str, harness: Harness) -> list[HumanUtterance]:
    """Automation-safe role-user rows; genuine repeated sends stay distinct."""
    return [
        utterance
        for utterance in extract_utterances(path, harness)
        if utterance.can_trigger_intervention
    ]
