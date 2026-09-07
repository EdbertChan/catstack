"""scratchpad-collision: two agents must not share one scratchpad file name.

Every agent in a session (the parent and each subagent) is handed the same
scratchpad directory. Two of them writing `pr-body.md` within minutes of
each other means one PR ships with the other's body. Before a Write, Edit,
or a Bash redirect into a scratchpad path, look at who wrote that file
last (a `.writers.json` sidecar this hook keeps in the scratchpad dir,
keyed by absolute path) and how long ago (the file's mtime). A different
writer inside the window blocks; the same writer, an unknown writer, an
older file, or a new file records the current writer and passes. Fails
open on any error.
"""
from __future__ import annotations

import json
import os
import re
import time

SCRATCHPAD_RE = re.compile(r"^(/private)?/tmp/claude-[^/]+/.*?/scratchpad(?=/|$)")
REDIRECT_RE = re.compile(r"(?:>>?|\btee(?:\s+-a)?|\bcp\s+\S+|\bmv\s+\S+)\s+([\w./~$-]+)")
QUOTED_PATH_RE = re.compile(r"[\"']([\w./~$-]+)[\"']")
SIDECAR = ".writers.json"
WINDOW_SECS = 10 * 60

MESSAGE = (
    "scratchpad-collision: another agent wrote {name} {age} s ago; use a uniquely named "
    "file (for example {suggest}) instead of sharing {name} (scratchpad-collision)."
)


def scratchpad_root(path: str) -> str | None:
    """The scratchpad directory this path lives in, or None."""
    absolute = os.path.abspath(os.path.expanduser(path))
    env_root = os.environ.get("CLAUDE_SCRATCHPAD")
    if env_root:
        env_root = os.path.abspath(env_root)
        if absolute == env_root or absolute.startswith(env_root + os.sep):
            return env_root
    match = SCRATCHPAD_RE.match(absolute)
    return match.group(0) if match else None


def target_paths(tool_name: str, tool_input: dict) -> list[str]:
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        for key in ("file_path", "path", "notebook_path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return [value]
        return []
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return []
        found = [m.group(1) for m in REDIRECT_RE.finditer(command)]
        found += [m.group(1) for m in QUOTED_PATH_RE.finditer(command) if "/" in m.group(1)]
        return [p for p in found if scratchpad_root(p)]
    return []


def writer_id(payload: dict) -> str:
    for key in ("agent_id", "agentId"):
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key]
    transcript = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(transcript, str) and transcript:
        return os.path.splitext(os.path.basename(transcript))[0]
    return str(payload.get("session_id") or payload.get("sessionId") or "unknown")


def _load_sidecar(root: str) -> dict:
    try:
        with open(os.path.join(root, SIDECAR), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sidecar(root: str, data: dict) -> None:
    path = os.path.join(root, SIDECAR)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(root, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def check_target(path: str, writer: str, now: float | None = None) -> str | None:
    """Block message when another writer touched this scratchpad file inside
    the window; otherwise record the writer and return None."""
    root = scratchpad_root(path)
    if not root:
        return None
    absolute = os.path.abspath(os.path.expanduser(path))
    now = time.time() if now is None else now
    sidecar = _load_sidecar(root)
    record = sidecar.get(absolute) if isinstance(sidecar.get(absolute), dict) else None
    try:
        age = now - os.stat(absolute).st_mtime
    except OSError:
        age = None
    if record and age is not None and age < WINDOW_SECS and record.get("writer") not in (None, writer):
        name = os.path.basename(absolute)
        stem, ext = os.path.splitext(name)
        return MESSAGE.format(name=name, age=int(max(age, 0)), suggest=f"{stem}-{writer[:8]}{ext}")
    sidecar[absolute] = {"writer": writer, "ts": now}
    _save_sidecar(root, sidecar)
    return None


def decide(payload: dict) -> str | None:
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    writer = writer_id(payload)
    for path in target_paths(tool_name, tool_input):
        message = check_target(path, writer)
        if message:
            return message
    return None
