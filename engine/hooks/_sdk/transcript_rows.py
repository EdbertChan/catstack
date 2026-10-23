"""Typed readers for Claude Code transcript rows (one JSON object per line)."""
from __future__ import annotations

import json
import sys

META_USER_PREFIXES = ("<task-notification", "<system-reminder", "<local-command", "Stop hook feedback")


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return ""


def read_lines(path: str) -> list[dict]:
    rows = []
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                data = json.loads(raw)
            except ValueError:
                skipped += 1
                continue
            if isinstance(data, dict):
                rows.append(data)
    if skipped:
        print(f"catstack-hook-error transcript_rows: skipped {skipped} unparseable line(s) in {path}", file=sys.stderr)
    return rows


def message(row: dict) -> dict:
    value = row.get("message")
    return value if isinstance(value, dict) else {}


def is_user_prompt(row: dict) -> bool:
    if row.get("type") != "user" or row.get("isMeta") or row.get("isSidechain"):
        return False
    content = message(row).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = content_text(content).strip()
    return bool(text) and not text.startswith(META_USER_PREFIXES)


def tool_uses(row: dict) -> list[dict]:
    if row.get("type") != "assistant":
        return []
    content = message(row).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def tool_results(row: dict) -> list[dict]:
    content = message(row).get("content")
    if row.get("type") != "user" or not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def user_prompts(rows: list[dict]) -> list[str]:
    return [content_text(message(r).get("content")).strip() for r in rows if is_user_prompt(r)]
