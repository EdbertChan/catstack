from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
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
    finding_id: str | None = None,
) -> list[dict[str, object]]:
    err = stderr if stderr is not None else sys.stderr
    rows = _rows(hook, harness, event, findings, mode, mode_source, duration_ms, action, finding_id)
    path = _event_path()
    try:
        _append_rows(path, rows)
        prune_old_event_files(stderr=err)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: event write failed: {type(exc).__name__}: {exc}", file=err)
        return []
    return rows


def write_followup_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    closures: Iterable[dict[str, object]],
    duration_ms: int,
    stderr: TextIO | None = None,
) -> None:
    rows = [
        _followup_row(hook, harness, event, closure, duration_ms)
        for closure in closures
    ]
    if not rows:
        return
    err = stderr if stderr is not None else sys.stderr
    try:
        _append_rows(_event_path(), rows)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: event write failed: {type(exc).__name__}: {exc}", file=err)


def prune_old_event_files(
    days: int = 30,
    stderr: TextIO | None = None,
    today: date | None = None,
) -> None:
    metrics_dir = _metrics_dir()
    marker = metrics_dir / ".last-event-prune"
    current_date = today if today is not None else datetime.now(timezone.utc).date()
    err = stderr if stderr is not None else sys.stderr
    try:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == current_date.isoformat():
            return
        marker.write_text(current_date.isoformat() + "\n", encoding="utf-8")
        cutoff = current_date - timedelta(days=days)
        for path in metrics_dir.glob("events-*.jsonl"):
            event_date = _event_file_date(path)
            if event_date is not None and event_date < cutoff:
                path.unlink()
    except Exception as exc:
        print(f"catstack-hook-error metrics: event prune failed: {type(exc).__name__}: {exc}", file=err)


def _rows(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
    action: str | None,
    finding_id: str | None,
) -> list[dict[str, object]]:
    if action is not None:
        rows_action = action
    else:
        rows_action = _action(mode)
    if not findings:
        return [_row(hook, harness, event, None, mode, mode_source, action or "silent", duration_ms, finding_id)]
    return [
        _row(hook, harness, event, finding, mode, mode_source, rows_action, duration_ms, finding_id)
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
    finding_id: str | None,
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
        "finding_id": finding_id if finding_id is not None else uuid.uuid4().hex,
        "duration_ms": duration_ms,
    }


def _followup_row(
    hook: str,
    harness: str,
    event: dict[str, object],
    closure: dict[str, object],
    duration_ms: int,
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": hook,
        "rule_id": str(closure.get("rule_id", "")),
        "subject_hash": str(closure.get("subject_hash", "")),
        "mode": "",
        "mode_source": "",
        "action": "followup",
        "finding_id": str(closure.get("finding_id", "")),
        "duration_ms": duration_ms,
        "outcome": str(closure.get("outcome", "")),
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


def _event_path() -> Path:
    return _metrics_dir() / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"


def _append_rows(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _event_file_date(path: Path) -> date | None:
    stem = path.name.removeprefix("events-").removesuffix(".jsonl")
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None
