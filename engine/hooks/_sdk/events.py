from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from finding import Finding

SCHEMA = "catstack.hook_event.v1"
DEFAULT_METRICS_DIR = Path.home() / ".cache" / "catstack-hook-metrics"


def write_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
    stderr: TextIO | None = None,
    action: str | None = None,
) -> None:
    err = stderr if stderr is not None else sys.stderr
    rows = _rows(hook, harness, event, findings, mode, mode_source, duration_ms, action)
    path = _metrics_dir() / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"catstack-hook-error {hook}: event write failed: {type(exc).__name__}: {exc}", file=err)


def _rows(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
    action: str | None,
) -> list[dict[str, object]]:
    if action is not None:
        rows_action = action
    else:
        rows_action = _action(mode)
    if not findings:
        return [_row(hook, harness, event, None, mode, mode_source, action or "silent", duration_ms)]
    return [
        _row(hook, harness, event, finding, mode, mode_source, rows_action, duration_ms)
        for finding in findings
    ]


def _row(
    hook: str,
    harness: str,
    event: dict[str, object],
    finding: Finding | None,
    mode: str,
    mode_source: str,
    action: str,
    duration_ms: int,
) -> dict[str, object]:
    subject = finding.subject if finding is not None else ""
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": hook,
        "rule_id": finding.rule_id if finding is not None else "",
        "subject_hash": _subject_hash(subject),
        "mode": mode,
        "mode_source": mode_source,
        "action": action,
        "finding_id": uuid.uuid4().hex,
        "duration_ms": duration_ms,
    }


def _session_id(event: dict[str, object]) -> str:
    for key in ("session_id", "sessionId", "session"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _action(mode: str) -> str:
    if mode == "stop":
        return "stopped"
    if mode == "warn":
        return "warned"
    return "silent"


def _metrics_dir() -> Path:
    return Path(os.environ.get("CATSTACK_HOOK_METRICS_DIR", DEFAULT_METRICS_DIR))
