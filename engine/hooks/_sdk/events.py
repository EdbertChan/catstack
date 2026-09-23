from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, TextIO

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
    if finding_id is not None and len(findings) != 1:
        raise ValueError("an explicit finding_id requires exactly one finding")
    rows = _rows(hook, harness, event, findings, mode, mode_source, duration_ms, action, finding_id)
    return rows if _append_rows(hook, rows, err) else []


def write_followup_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    closures: list[Mapping[str, object]],
    stderr: TextIO | None = None,
) -> None:
    err = stderr if stderr is not None else sys.stderr
    rows = [_followup_row(hook, harness, event, closure) for closure in closures]
    _append_rows(hook, rows, err)


def write_stage_event(
    hook: str,
    harness: str,
    session_id: str,
    action: str,
    reason: str,
    finding_id: str | None = None,
    stderr: TextIO | None = None,
) -> bool:
    err = stderr if stderr is not None else sys.stderr
    row = _row(hook, harness, {"session_id": session_id}, None, "", "stage", action, 0, finding_id)
    row["reason"] = reason
    return _append_rows(hook, [row], err)


def prune_old_event_files(days: int = 30, stderr: TextIO | None = None) -> None:
    err = stderr if stderr is not None else sys.stderr
    root = _metrics_dir()
    today = datetime.now(timezone.utc).date()
    marker = root / f".events-pruned-{today.isoformat()}"
    if marker.exists():
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        cutoff = today - timedelta(days=days)
        for path in root.glob("events-*.jsonl"):
            file_date = _event_file_date(path)
            if file_date is not None and file_date < cutoff:
                path.unlink()
    except OSError as exc:
        print(f"catstack-hook-error metrics: event prune failed: {type(exc).__name__}: {exc}", file=err)


def _append_rows(hook: str, rows: list[dict[str, object]], err: TextIO) -> bool:
    path = _metrics_dir() / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"catstack-hook-error {hook}: event write failed: {type(exc).__name__}: {exc}", file=err)
        return False
    else:
        prune_old_event_files(stderr=err)
        return True


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
        "finding_id": finding_id or uuid.uuid4().hex,
        "duration_ms": duration_ms,
    }


def _followup_row(
    hook: str,
    harness: str,
    event: dict[str, object],
    closure: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": str(closure.get("hook", hook)),
        "rule_id": str(closure.get("rule_id", "")),
        "subject_hash": str(closure.get("subject_hash", "")),
        "mode": str(closure.get("mode", "")),
        "mode_source": str(closure.get("mode_source", "")),
        "action": "followup",
        "finding_id": str(closure.get("finding_id", "")),
        "duration_ms": 0,
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


def _event_file_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem.removeprefix("events-"))
    except ValueError:
        return None
