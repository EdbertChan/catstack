from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import TextIO

import registry
from events import DEFAULT_METRICS_DIR, write_followup_events

MODE_RANK = {"off": 0, "warn": 1, "stop": 2}


def record_followups(
    hook: str,
    harness: str,
    event: dict[str, object],
    finding_rows: list[dict[str, object]],
    mode: str,
    mode_source: str,
    duration_ms: int,
    stderr: TextIO | None = None,
) -> None:
    err = stderr if stderr is not None else sys.stderr
    state_path = _state_path(event)
    open_findings, readable = _read_state(state_path)
    if not readable:
        write_followup_events(
            hook,
            harness,
            event,
            [{"finding_id": "", "rule_id": "", "subject_hash": "", "outcome": "unchecked"}],
            duration_ms,
            err,
        )
        open_findings = []

    try:
        loaded = registry.load_registry(_registry_path(event))
        followup_window_checks = loaded.thresholds.followup_window_checks
        registry_mode = loaded.hooks[hook].mode
    except registry.RegistryError as exc:
        print(f"catstack-hook-error {hook}: followup registry failed: {type(exc).__name__}: {exc}", file=err)
        return

    current_findings = _current_findings(hook, finding_rows)
    current_keys = {
        _key(row)
        for row in current_findings
    }
    override_lower = mode_source == "override" and _mode_rank(mode) < _mode_rank(registry_mode)
    session_end = _is_session_end(event)
    closures: list[dict[str, object]] = []
    next_open: list[dict[str, object]] = []

    for item in open_findings:
        if item.get("hook") != hook:
            next_open.append(item)
            continue
        key = _key(item)
        if override_lower and key in current_keys:
            closures.append(_closure(item, "overridden"))
            continue
        if key in current_keys:
            closures.append(_closure(item, "ignored"))
            continue

        updated = dict(item)
        updated["checks_since"] = int(updated.get("checks_since", 0)) + 1
        if updated["checks_since"] >= followup_window_checks:
            closures.append(_closure(updated, "acted"))
        else:
            next_open.append(updated)

    for row in current_findings:
        if row.get("action") in {"stopped", "warned"}:
            next_open.append(
                {
                    "finding_id": str(row.get("finding_id", "")),
                    "hook": hook,
                    "rule_id": str(row.get("rule_id", "")),
                    "subject_hash": str(row.get("subject_hash", "")),
                    "checks_since": 0,
                }
            )

    if session_end:
        still_open: list[dict[str, object]] = []
        for item in next_open:
            if item.get("hook") == hook:
                closures.append(_closure(item, "acted"))
            else:
                still_open.append(item)
        next_open = still_open

    write_followup_events(hook, harness, event, closures, duration_ms, err)
    _write_state(state_path, next_open, hook, err)


def _current_findings(hook: str, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row.get("hook") == hook
        and isinstance(row.get("rule_id"), str)
        and row.get("rule_id")
        and isinstance(row.get("subject_hash"), str)
        and row.get("subject_hash")
    ]


def _read_state(path: Path) -> tuple[list[dict[str, object]], bool]:
    if not path.exists():
        return [], True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], False
    if not isinstance(raw, list):
        return [], False
    rows: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            return [], False
        if not _valid_state_row(item):
            return [], False
        rows.append(dict(item))
    return rows, True


def _valid_state_row(item: dict[str, object]) -> bool:
    return (
        isinstance(item.get("finding_id"), str)
        and isinstance(item.get("hook"), str)
        and isinstance(item.get("rule_id"), str)
        and isinstance(item.get("subject_hash"), str)
        and isinstance(item.get("checks_since"), int)
    )


def _write_state(path: Path, rows: list[dict[str, object]], hook: str, stderr: TextIO) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"catstack-hook-error {hook}: followup state write failed: {type(exc).__name__}: {exc}", file=stderr)


def _state_path(event: dict[str, object]) -> Path:
    session_id = _session_id(event)
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _metrics_dir() / "followup" / f"session-{digest}.json"


def _metrics_dir() -> Path:
    return Path(os.environ.get("CATSTACK_HOOK_METRICS_DIR", DEFAULT_METRICS_DIR))


def _session_id(event: dict[str, object]) -> str:
    for key in ("session_id", "sessionId", "session"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _registry_path(event: dict[str, object]) -> str | Path | None:
    path = event.get("registry_path")
    if isinstance(path, str) and path:
        return path
    return None


def _is_session_end(event: dict[str, object]) -> bool:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value.lower().replace("_", "") == "sessionend":
            return True
    return False


def _closure(item: dict[str, object], outcome: str) -> dict[str, object]:
    return {
        "finding_id": str(item.get("finding_id", "")),
        "rule_id": str(item.get("rule_id", "")),
        "subject_hash": str(item.get("subject_hash", "")),
        "outcome": outcome,
    }


def _key(item: dict[str, object]) -> tuple[object, object]:
    return (item.get("rule_id"), item.get("subject_hash"))


def _mode_rank(mode: str) -> int:
    return MODE_RANK.get(mode, -1)
