from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from detect import notice, unreadable_notice


def metrics_dir() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root)


def session_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    value = payload.get("session_id")
    if value is None:
        value = payload.get("conversation_id")
    if value is None:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))[:160] or "unknown"


def cursor_path(root: Path, harness: str, session: str) -> Path:
    return root / f"hook-health-{harness}-{session}.json"


def read_offset(path: Path) -> int:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0
    offset = data.get("offset") if isinstance(data, dict) else None
    if isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0:
        return offset
    return 0


def write_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"offset": offset}, handle, sort_keys=True)
        handle.write("\n")


def read_rows_from(path: Path, offset: int) -> tuple[list[dict[str, Any]], int, str | None]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return [], offset, None
    except OSError as exc:
        return [], offset, str(exc)
    if offset > size:
        offset = 0
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
            end = handle.tell()
    except OSError as exc:
        return [], offset, str(exc)
    rows = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, end, None


def emit_notice(harness: str, text: str) -> None:
    if harness in {"claude", "codex"}:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": text,
                    }
                }
            )
        )
    else:
        print(json.dumps({"continue": True, "additional_context": text}))


def run(harness: str, payload: object) -> None:
    root = metrics_dir()
    log = root / "runs.jsonl"
    state = cursor_path(root, harness, session_id(payload))
    offset = read_offset(state)
    rows, new_offset, error = read_rows_from(log, offset)
    if error is not None:
        emit_notice(harness, unreadable_notice(str(log), error))
        return
    if new_offset != offset:
        write_offset(state, new_offset)
    text = notice(rows, harness)
    if text is not None:
        emit_notice(harness, text)


def main(harness: str) -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        sys.stderr.write(f"catstack-hook-error hook-health: {type(exc).__name__}: {exc}\n")
        return
    try:
        run(harness, payload)
    except Exception as exc:
        sys.stderr.write(f"catstack-hook-error hook-health: {type(exc).__name__}: {exc}\n")
