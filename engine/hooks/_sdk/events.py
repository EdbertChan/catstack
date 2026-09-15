"""Write hook finding events."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from uuid import uuid4
from datetime import datetime, timezone

from engine.hooks._sdk.finding import Finding

SCHEMA = "catstack.hook-event.v1"
DEFAULT_DIR = Path.home() / ".cache" / "catstack-hook-metrics"


def metrics_dir() -> Path:
    return Path(os.environ.get("CATSTACK_HOOK_METRICS_DIR", DEFAULT_DIR))


def action_for(mode: str, findings: list[Finding]) -> str:
    if not findings or mode == "off":
        return "silent"
    if mode == "stop":
        return "stopped"
    if mode == "warn":
        return "warned"
    return "unchecked"


def subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8", "replace")).hexdigest()


def _session_id(event: dict | None) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("session_id") or event.get("sessionId") or "")


def _rows(
    hook: str,
    harness: str,
    event: dict | None,
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    machine = socket.gethostname()
    action = action_for(mode, findings)
    if not findings:
        findings = [Finding("", "", "", "")]
    return [
        {
            "schema": SCHEMA,
            "ts": now,
            "machine": machine,
            "harness": harness,
            "session_id": _session_id(event),
            "hook": hook,
            "rule_id": finding.rule_id,
            "subject_hash": subject_hash(finding.subject),
            "mode": mode,
            "mode_source": mode_source,
            "action": action,
            "finding_id": uuid4().hex,
            "duration_ms": duration_ms,
        }
        for finding in findings
    ]


def append_events(
    hook: str,
    harness: str,
    event: dict | None,
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
) -> None:
    try:
        directory = metrics_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for row in _rows(hook, harness, event, findings, mode, mode_source, duration_ms):
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as exc:
        print(f"catstack-hook-error events: {type(exc).__name__}: {exc}", file=sys.stderr)
