from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding

BUDGET_ENV = "CATSTACK_AGENT_LAUNCH_BUDGET"
LEDGER_ENV = "CATSTACK_AGENT_LAUNCH_LEDGER"
DEFAULT_WINDOW_SECS = 600.0
DEFAULT_LEDGER = os.path.expanduser("~/.catstack/agent-launch-ledger.jsonl")
RULE_ID = "agent-launch-guard.rate"


@dataclass(frozen=True)
class Budget:
    maximum: int
    window_secs: float


def _error(message: str) -> None:
    print(f"catstack-hook-error agent-launch-guard: {message}", file=sys.stderr)


def parse_budget(value: str | None) -> Budget | None:
    if value is None or value.strip().lower() in {"", "off"}:
        return None
    parts = value.split(":")
    if len(parts) > 2:
        return None
    try:
        maximum = int(parts[0])
        window_secs = float(parts[1]) if len(parts) == 2 else DEFAULT_WINDOW_SECS
    except ValueError:
        return None
    if maximum < 1 or window_secs <= 0:
        return None
    return Budget(maximum, window_secs)


def _tool_name(event: dict) -> str:
    value = event.get("tool_name") or event.get("toolName") or event.get("tool")
    return value if isinstance(value, str) else ""


def _tool_input(event: dict) -> dict:
    value = event.get("tool_input") or event.get("toolInput") or event.get("arguments")
    return value if isinstance(value, dict) else {}


def _description(event: dict) -> str:
    value = _tool_input(event).get("description")
    if not isinstance(value, str):
        value = _tool_input(event).get("prompt")
    return value if isinstance(value, str) else ""


def _session_id(event: dict) -> str:
    value = event.get("session_id") or event.get("sessionId")
    return value if isinstance(value, str) else ""


def _ledger_path() -> str:
    return os.environ.get(LEDGER_ENV) or DEFAULT_LEDGER


def _read_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"ledger row {line_number} is not an object")
            rows.append(row)
    return rows


def _write_rows(path: str, rows: list[dict]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _event_row(event: dict, timestamp: float) -> dict:
    description = _description(event).encode("utf-8")
    return {
        "ts": timestamp,
        "session_id": _session_id(event),
        "tool_use_id": event.get("tool_use_id") or event.get("toolUseId"),
        "description_sha": hashlib.sha256(description).hexdigest(),
    }


def detect(event: dict, now: float | None = None) -> list[Finding]:
    budget = parse_budget(os.environ.get(BUDGET_ENV))
    if budget is None or _tool_name(event) not in {"Agent", "Task"}:
        return []
    timestamp = time.time() if now is None else now
    path = _ledger_path()
    try:
        rows = _read_rows(path)
        cutoff = timestamp - budget.window_secs
        rows = [row for row in rows if isinstance(row.get("ts"), (int, float)) and row["ts"] >= cutoff]
        row = _event_row(event, timestamp)
        rows.append(row)
        _write_rows(path, rows)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _error(f"ledger failure ({path}): {exc}")
        return []

    session_id = row["session_id"]
    session_rows = [
        item for item in rows
        if item.get("session_id") == session_id and item.get("ts", 0) >= cutoff
    ]
    if len(session_rows) != budget.maximum + 1:
        return []
    return [
        Finding(
            rule_id=RULE_ID,
            subject=f"session:{session_id}",
            message=(
                f"Agent launch budget exceeded: session {session_id or '<unknown>'} has "
                f"{len(session_rows)} launches in {int(budget.window_secs)} seconds "
                f"(budget {budget.maximum}); launch continues."
            ),
            evidence=json.dumps(row, sort_keys=True),
        )
    ]
