"""new-file-callout: a new file at the repo root or under scripts/ must be
named in the reply that leaves it there.

A file the user did not ask for, dropped at the top of their repo by a
Write, a shell redirect, or a subagent, is a surprise at review time
("wtf is install_cursor_session_hygiene.py?"). At Stop, list the untracked
files at the repo root and under a top-level scripts/ that this turn
touched (referenced in a tool input, tool result, or task notification, or
modified since the turn began) and require the reply to name each one.
Judgment (is the reason good) stays with the model; this file matches
shapes and fails open.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime

REDIRECT_RE = re.compile(r"(?:>>?|\btee(?:\s+-a)?|\btouch|\bcp\s+\S+|\bmv\s+\S+|\binstall\s+(?:-\S+\s+)*\S+)\s+([\w./~$-]+)")
QUOTED_PATH_RE = re.compile(r"[\"']([\w./~$-]+\.(?:py|sh|md|json|ts|js|mjs|yml|yaml|toml|txt))[\"']")
TOP_LEVEL_DIRS = ("scripts",)

MESSAGE = (
    "new-file-callout: this turn left untracked file(s) at the repo root or under scripts/ "
    "that the reply does not name: {files}. Name each one with why it exists "
    "(or delete it) before ending the turn."
)


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    parts.append(inner)
                elif isinstance(inner, list):
                    parts.extend(b.get("text", "") for b in inner if isinstance(b, dict))
        return "\n".join(parts)
    return ""


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    text = _text_content(data)
    return bool(text.strip()) and not text.lstrip().startswith("<")


def parse_lines(raw_lines) -> list[dict]:
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def _parse_ts(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def turn_context(lines: list[dict]) -> dict:
    """Paths named by this turn's tool inputs, all text seen this turn, and
    the turn's start time (epoch seconds, or None)."""
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    started_at = _parse_ts(lines[turn_start].get("timestamp")) if lines else None
    paths: set[str] = set()
    text_parts: list[str] = []
    for data in lines[turn_start:]:
        text_parts.append(_text_content(data))
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inp = block.get("input") or {}
            for key in ("file_path", "path", "notebook_path"):
                if isinstance(inp.get(key), str):
                    paths.add(inp[key])
            command = inp.get("command")
            if isinstance(command, str):
                paths.update(m.group(1) for m in REDIRECT_RE.finditer(command))
                paths.update(m.group(1) for m in QUOTED_PATH_RE.finditer(command))
                text_parts.append(command)
            prompt = inp.get("prompt")
            if isinstance(prompt, str):
                text_parts.append(prompt)
    return {"paths": paths, "text": "\n".join(text_parts), "started_at": started_at}


def untracked_top_level(cwd: str) -> tuple[str, list[str]] | None:
    """(repo root, untracked repo-relative paths at the root or under a
    top-level scripts/). None when cwd is not inside a git repo."""
    try:
        root = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5,
        )
        if root.returncode != 0:
            return None
        repo = root.stdout.strip()
        status = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if status.returncode != 0:
        return None
    found: list[str] = []
    for raw in status.stdout.splitlines():
        if not raw.startswith("??"):
            continue
        rel = raw[3:].strip().strip('"')
        parts = rel.split("/")
        if len(parts) == 1 or (parts[0] in TOP_LEVEL_DIRS and len(parts) >= 2):
            found.append(rel)
    return repo, found


def files_needing_callout(repo: str, untracked: list[str], ctx: dict) -> list[str]:
    out: list[str] = []
    for rel in untracked:
        base = os.path.basename(rel)
        absolute = os.path.join(repo, rel)
        referenced = any(p.endswith(rel) or os.path.basename(p) == base for p in ctx["paths"])
        mentioned = base in ctx["text"]
        fresh = False
        if ctx["started_at"] is not None:
            try:
                fresh = os.stat(absolute).st_mtime >= ctx["started_at"]
            except OSError:
                fresh = False
        if referenced or mentioned or fresh:
            out.append(rel)
    return out


def unnamed_in_reply(reply: str, files: list[str]) -> list[str]:
    return [rel for rel in files if os.path.basename(rel) not in (reply or "")]


def decide_from_lines(message: str, lines: list[dict], cwd: str) -> str | None:
    found = untracked_top_level(cwd)
    if not found:
        return None
    repo, untracked = found
    if not untracked:
        return None
    ctx = turn_context(lines)
    missing = unnamed_in_reply(message, files_needing_callout(repo, untracked, ctx))
    if not missing:
        return None
    return MESSAGE.format(files=", ".join(f"`{m}`" for m in missing))


def decide(payload: dict) -> str | None:
    """Return blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    cwd = payload.get("cwd") or os.getcwd()
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    lines: list[dict] = []
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    return decide_from_lines(payload.get("last_assistant_message") or "", lines, cwd)
