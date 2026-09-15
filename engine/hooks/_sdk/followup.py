from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import events
import registry


ACTIVE_ACTIONS = {"warned", "stopped"}
MODE_RANK = {"off": 0, "warn": 1, "stop": 2}
TERMINAL_EVENTS = {"sessionend", "session_end"}


def _session_id(event: dict[str, Any]) -> str:
    value = event.get("session_id") or event.get("sessionId") or event.get("conversation_id") or ""
    return str(value)


def _state_path(session_id: str) -> Path:
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return events.metrics_dir() / f"followup-{session_key}.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"open": []}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("open"), list):
        raise ValueError("follow-up state is not an object with an open list")
    return data


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def _finding_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row.get("rule_id") and row.get("subject_hash") and row.get("action") != "followup"
    ]


def _close_row(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
    item: dict[str, Any],
    outcome: str,
) -> dict[str, object]:
    return events.followup_row(
        event=event,
        harness=harness,
        hook=hook,
        rule_id=str(item.get("rule_id", "")),
        subject_hash=str(item.get("subject_hash", "")),
        mode=mode,
        mode_source=mode_source,
        finding_id=str(item.get("finding_id", "")),
        outcome=outcome,
    )


def _unchecked_row(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
) -> dict[str, object]:
    return events.followup_row(
        event=event,
        harness=harness,
        hook=hook,
        rule_id="",
        subject_hash="",
        mode=mode,
        mode_source=mode_source,
        finding_id="",
        outcome="unchecked",
    )


def _registry_mode(hook: str) -> str:
    try:
        return registry.load_registry().hooks[hook].mode
    except Exception:
        return "off"


def _lower_override(hook: str, mode: str, mode_source: str) -> bool:
    if mode_source != "override":
        return False
    return MODE_RANK.get(mode, 0) < MODE_RANK.get(_registry_mode(hook), 0)


def _event_name(event: dict[str, Any]) -> str:
    return str(
        event.get("hook_event_name")
        or event.get("hookEventName")
        or event.get("event_name")
        or event.get("event")
        or event.get("type")
        or ""
    )


def update_followups(
    *,
    event: dict[str, Any],
    harness: str,
    hook: str,
    mode: str,
    mode_source: str,
    rows: list[dict[str, object]],
    followup_window_checks: int,
) -> None:
    session_id = _session_id(event)
    path = _state_path(session_id)
    try:
        state = _load_state(path)
    except Exception as exc:
        events.append_event_rows(
            [
                _unchecked_row(
                    event=event,
                    harness=harness,
                    hook=hook,
                    mode=mode,
                    mode_source=mode_source,
                )
            ]
        )
        print(f"catstack-hook-error followup: {type(exc).__name__}: {exc}", file=sys.stderr)
        return

    current_rows = _finding_rows(rows)
    current_keys = {
        (str(row["rule_id"]), str(row["subject_hash"]))
        for row in current_rows
    }
    touched_subjects = {str(row["subject_hash"]) for row in current_rows}
    lower_override = _lower_override(hook, mode, mode_source)

    remaining: list[dict[str, Any]] = []
    closing_rows: list[dict[str, object]] = []
    for item in state.get("open", []):
        if not isinstance(item, dict):
            continue
        if item.get("hook") != hook:
            remaining.append(item)
            continue

        key = (str(item.get("rule_id", "")), str(item.get("subject_hash", "")))
        subject_hash = str(item.get("subject_hash", ""))
        if lower_override and subject_hash in touched_subjects:
            closing_rows.append(
                _close_row(
                    event=event,
                    harness=harness,
                    hook=hook,
                    mode=mode,
                    mode_source=mode_source,
                    item=item,
                    outcome="overridden",
                )
            )
            continue
        if key in current_keys:
            closing_rows.append(
                _close_row(
                    event=event,
                    harness=harness,
                    hook=hook,
                    mode=mode,
                    mode_source=mode_source,
                    item=item,
                    outcome="ignored",
                )
            )
            continue

        checks_since = int(item.get("checks_since", 0)) + 1
        if checks_since >= followup_window_checks:
            closing_rows.append(
                _close_row(
                    event=event,
                    harness=harness,
                    hook=hook,
                    mode=mode,
                    mode_source=mode_source,
                    item=item,
                    outcome="acted",
                )
            )
            continue
        item["checks_since"] = checks_since
        remaining.append(item)

    if _event_name(event).lower() in TERMINAL_EVENTS:
        still_open: list[dict[str, Any]] = []
        for item in remaining:
            if item.get("hook") == hook:
                closing_rows.append(
                    _close_row(
                        event=event,
                        harness=harness,
                        hook=hook,
                        mode=mode,
                        mode_source=mode_source,
                        item=item,
                        outcome="acted",
                    )
                )
            else:
                still_open.append(item)
        remaining = still_open

    if not lower_override:
        seen_new_keys: set[tuple[str, str]] = set()
        for row in current_rows:
            if row.get("action") not in ACTIVE_ACTIONS:
                continue
            key = (str(row["rule_id"]), str(row["subject_hash"]))
            if key in seen_new_keys:
                continue
            seen_new_keys.add(key)
            remaining.append(
                {
                    "finding_id": str(row["finding_id"]),
                    "hook": hook,
                    "rule_id": str(row["rule_id"]),
                    "subject_hash": str(row["subject_hash"]),
                    "checks_since": 0,
                }
            )

    state["open"] = remaining
    try:
        _save_state(path, state)
    except Exception as exc:
        print(f"catstack-hook-error followup: {type(exc).__name__}: {exc}", file=sys.stderr)

    if closing_rows:
        events.append_event_rows(closing_rows)
