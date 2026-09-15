from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any
from uuid import uuid4

from finding import Finding


SCHEMA = "catstack.hook.finding.v1"
DEFAULT_METRICS_DIR = Path.home() / ".cache" / "catstack-hook-metrics"
EVENT_PREFIX = "events-"
EVENT_SUFFIX = ".jsonl"


def metrics_dir() -> Path:
    configured = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_METRICS_DIR


def _subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _session_id(event: dict[str, Any]) -> str:
    value = event.get("session_id") or event.get("sessionId") or event.get("conversation_id") or ""
    return str(value)


def _action(mode: str) -> str:
    if mode == "stop":
        return "stopped"
    if mode == "warn":
        return "warned"
    return "silent"


def _row(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    rule_id: str,
    subject: str,
    mode: str,
    mode_source: str,
    action: str,
    duration_ms: int,
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": hook,
        "rule_id": rule_id,
        "subject_hash": _subject_hash(subject),
        "mode": mode,
        "mode_source": mode_source,
        "action": action,
        "finding_id": uuid4().hex,
        "duration_ms": duration_ms,
    }


def followup_row(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    rule_id: str,
    subject_hash: str,
    mode: str,
    mode_source: str,
    finding_id: str,
    outcome: str,
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": hook,
        "rule_id": rule_id,
        "subject_hash": subject_hash,
        "mode": mode,
        "mode_source": mode_source,
        "action": "followup",
        "finding_id": finding_id,
        "outcome": outcome,
        "duration_ms": 0,
    }


def event_rows(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
    findings: list[Finding],
    duration_ms: int,
) -> list[dict[str, object]]:
    if not findings:
        return [
            _row(
                event=event,
                harness=harness,
                hook=hook,
                rule_id="",
                subject="",
                mode=mode,
                mode_source=mode_source,
                action="silent",
                duration_ms=duration_ms,
            )
        ]
    action = _action(mode)
    return [
        _row(
            event=event,
            harness=harness,
            hook=hook,
            rule_id=finding.rule_id,
            subject=finding.subject,
            mode=mode,
            mode_source=mode_source,
            action=action,
            duration_ms=duration_ms,
        )
        for finding in findings
    ]


def _event_file_date(path: Path) -> datetime.date | None:
    name = path.name
    if not name.startswith(EVENT_PREFIX) or not name.endswith(EVENT_SUFFIX):
        return None
    raw = name[len(EVENT_PREFIX) : -len(EVENT_SUFFIX)]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def prune_old_event_files(days: int = 30) -> None:
    directory = metrics_dir()
    today = datetime.now(timezone.utc).date()
    marker = directory / f".events-pruned-{today.isoformat()}"
    if marker.exists():
        return

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"catstack-hook-error events-prune: {type(exc).__name__}: {exc}", file=sys.stderr)
        return

    cutoff = today - timedelta(days=days)
    for path in directory.glob(f"{EVENT_PREFIX}*{EVENT_SUFFIX}"):
        file_date = _event_file_date(path)
        if file_date is None or file_date >= cutoff:
            continue
        try:
            path.unlink()
        except Exception as exc:
            print(f"catstack-hook-error events-prune: {type(exc).__name__}: {exc}", file=sys.stderr)

    try:
        marker.write_text(today.isoformat() + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"catstack-hook-error events-prune: {type(exc).__name__}: {exc}", file=sys.stderr)


def append_event_rows(rows: list[dict[str, object]]) -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    path = metrics_dir() / f"{EVENT_PREFIX}{today}{EVENT_SUFFIX}"
    try:
        prune_old_event_files()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except Exception as exc:
        print(f"catstack-hook-error events: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def append_events(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
    findings: list[Finding],
    duration_ms: int,
) -> list[dict[str, object]]:
    rows = event_rows(
        event=event,
        harness=harness,
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        findings=findings,
        duration_ms=duration_ms,
    )
    return rows if append_event_rows(rows) else []
