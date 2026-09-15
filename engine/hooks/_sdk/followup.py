from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TextIO

import events
import registry

MODE_RANK = {"off": 0, "warn": 1, "stop": 2}


def update_followups(
    hook: str,
    harness: str,
    event: dict[str, object],
    event_rows: list[dict[str, object]],
    mode: str,
    mode_source: str,
    stderr: TextIO | None = None,
) -> None:
    session_id = events._session_id(event)
    state_path = _state_path(session_id)
    err = stderr
    state = _read_state(state_path)
    if state is None:
        events.write_followup_events(
            hook,
            harness,
            event,
            [_closure(hook, "", "", "", "unchecked", mode, mode_source)],
            err,
        )
        state = {"open": []}

    current = _current_findings(event_rows)
    current_keys = {(row["rule_id"], row["subject_hash"]) for row in current}
    lower_override = mode_source == "override" and _mode_rank(mode) < _mode_rank(_registry_mode(hook, event, mode))
    window = _followup_window(event)
    session_end = _is_session_end(event)

    next_open: list[dict[str, object]] = []
    closures: list[dict[str, object]] = []
    for finding in state.get("open", []):
        if not isinstance(finding, dict) or finding.get("hook") != hook:
            next_open.append(finding)
            continue

        key = (str(finding.get("rule_id", "")), str(finding.get("subject_hash", "")))
        if lower_override and key in current_keys:
            closures.append(_from_finding(finding, "overridden", mode, mode_source))
            continue
        if key in current_keys:
            closures.append(_from_finding(finding, "ignored", mode, mode_source))
            continue
        if session_end:
            closures.append(_from_finding(finding, "acted", mode, mode_source))
            continue

        checks_since = _checks_since(finding) + 1
        if checks_since >= window:
            closures.append(_from_finding(finding, "acted", mode, mode_source))
            continue
        finding["checks_since"] = checks_since
        next_open.append(finding)

    next_open.extend(_new_open_findings(current))
    if closures:
        events.write_followup_events(hook, harness, event, closures, err)
    _write_state(state_path, {"open": next_open}, hook, err)


def _read_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return {"open": []}
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, UnicodeError):
        return None
    if not isinstance(state, dict) or not isinstance(state.get("open", []), list):
        return None
    return state


def _write_state(path: Path, state: dict[str, object], hook: str, stderr: TextIO | None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
    except (OSError, TypeError, ValueError) as exc:
        err = stderr if stderr is not None else sys.stderr
        print(f"catstack-hook-error {hook}: followup state write failed: {type(exc).__name__}: {exc}", file=err)


def _current_findings(event_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    findings = []
    for row in event_rows:
        rule_id = row.get("rule_id")
        subject_hash = row.get("subject_hash")
        finding_id = row.get("finding_id")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        if not isinstance(subject_hash, str) or not subject_hash:
            continue
        if not isinstance(finding_id, str) or not finding_id:
            continue
        findings.append(
            {
                "finding_id": finding_id,
                "hook": str(row.get("hook", "")),
                "rule_id": rule_id,
                "subject_hash": subject_hash,
                "action": str(row.get("action", "")),
            }
        )
    return findings


def _new_open_findings(findings: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "finding_id": finding["finding_id"],
            "hook": finding["hook"],
            "rule_id": finding["rule_id"],
            "subject_hash": finding["subject_hash"],
            "checks_since": 0,
        }
        for finding in findings
        if finding["action"] in {"warned", "stopped"}
    ]


def _from_finding(
    finding: dict[str, object],
    outcome: str,
    mode: str,
    mode_source: str,
) -> dict[str, object]:
    return _closure(
        str(finding.get("hook", "")),
        str(finding.get("finding_id", "")),
        str(finding.get("rule_id", "")),
        str(finding.get("subject_hash", "")),
        outcome,
        mode,
        mode_source,
    )


def _closure(
    hook: str,
    finding_id: str,
    rule_id: str,
    subject_hash: str,
    outcome: str,
    mode: str,
    mode_source: str,
) -> dict[str, object]:
    return {
        "hook": hook,
        "finding_id": finding_id,
        "rule_id": rule_id,
        "subject_hash": subject_hash,
        "outcome": outcome,
        "mode": mode,
        "mode_source": mode_source,
    }


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id) or "unknown-session"
    return events._metrics_dir() / "followup" / f"{safe}.json"


def _registry_mode(hook: str, event: dict[str, object], fallback: str) -> str:
    path = event.get("registry_path") if isinstance(event, dict) else None
    try:
        hooks, _thresholds = registry.load_registry(path)
    except registry.RegistryError:
        return fallback
    record = hooks.get(hook)
    return record.mode if record is not None else fallback


def _followup_window(event: dict[str, object]) -> int:
    path = event.get("registry_path") if isinstance(event, dict) else None
    try:
        _hooks, thresholds = registry.load_registry(path)
    except registry.RegistryError:
        return 3
    return thresholds.followup_window_checks


def _mode_rank(mode: str) -> int:
    return MODE_RANK.get(mode, -1)


def _checks_since(finding: dict[str, object]) -> int:
    value = finding.get("checks_since", 0)
    return value if isinstance(value, int) else 0


def _is_session_end(event: dict[str, object]) -> bool:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value.lower() in {"stop", "sessionend", "session_end"}:
            return True
    return False
