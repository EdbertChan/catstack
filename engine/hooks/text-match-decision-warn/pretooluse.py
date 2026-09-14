"""Shared PreToolUse body for the Claude, Cursor, and Codex entrypoints.

Never blocks. A hit prints one advisory message on stdout (so the metrics
runner records outcome `spoke`) and appends one JSONL row per hit to the
warning log next to the runner's runs.jsonl.
"""
from __future__ import annotations

import datetime
import json
import os
import sys

from detect import HOOK, Scan, evaluate, format_message

LOG_NAME = f"{HOOK}-warnings.jsonl"


def warnings_log_path() -> str:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if not root:
        root = os.path.expanduser(os.path.join("~", ".cache", "catstack-hook-metrics"))
    return os.path.join(root, LOG_NAME)


def _session_id(payload: dict) -> object:
    for key in ("session_id", "conversation_id", "sessionId", "conversationId"):
        if payload.get(key) is not None:
            return payload[key]
    return None


def _tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or payload.get("name") or "")


def warning_rows(payload: dict, harness: str, scan: Scan) -> list[dict]:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return [
        {
            "ts": ts,
            "hook": HOOK,
            "harness": harness,
            "session_id": _session_id(payload),
            "tool": _tool_name(payload),
            "file_path": hit.file_path,
            "line_no": hit.line_no,
            "line": hit.line,
            "rule": hit.rule,
            "scope": hit.scope,
            "baseline": hit.baseline,
        }
        for hit in scan.hits
    ]


def append_rows(rows: list[dict]) -> str | None:
    path = warnings_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        return f"catstack-hook-error {HOOK}: could not write warning log to {path}: {exc}"
    return None


def emit(harness: str, message: str) -> None:
    if harness == "cursor":
        print(json.dumps({"permission": "allow", "agent_message": message}))
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}))
    if harness == "codex":
        sys.stderr.write(message + "\n")


def main(harness: str) -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"catstack-hook-error {HOOK}: unreadable hook payload, nothing checked: {exc}\n")
        return
    if not isinstance(payload, dict):
        sys.stderr.write(f"catstack-hook-error {HOOK}: hook payload is not a JSON object, nothing checked\n")
        return
    try:
        scan = evaluate(payload)
    except Exception as exc:
        sys.stderr.write(f"catstack-hook-error {HOOK}: scanner error, nothing checked: {type(exc).__name__}: {exc}\n")
        return
    for note in scan.unchecked:
        sys.stderr.write(f"{HOOK}: unchecked: {note}\n")
    if not scan.hits:
        return
    error = append_rows(warning_rows(payload, harness, scan))
    if error:
        sys.stderr.write(error + "\n")
    emit(harness, format_message(scan.hits))
