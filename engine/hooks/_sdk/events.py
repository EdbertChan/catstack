from __future__ import annotations

from datetime import datetime, timezone
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


def append_events(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
    findings: list[Finding],
    duration_ms: int,
) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    path = metrics_dir() / f"events-{today}.jsonl"
    rows = event_rows(
        event=event,
        harness=harness,
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        findings=findings,
        duration_ms=duration_ms,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as exc:
        print(f"catstack-hook-error events: {type(exc).__name__}: {exc}", file=sys.stderr)
