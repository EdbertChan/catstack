from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding  # noqa: E402

FAILURES = {"crashed", "timed_out", "caught_error"}
RULE_FAILED_RUN = "hook-health.failed-run"
RULE_UNREADABLE_LOG = "hook-health.unreadable-log"


def first_stderr_line(row: dict) -> str:
    tail = row.get("stderr_tail")
    if not isinstance(tail, str):
        return ""
    for line in tail.splitlines():
        if line.strip():
            return line.strip()
    return ""


def notice(rows: list[dict], harness: str) -> str | None:
    failures = failed_rows(rows, harness)
    if not failures:
        return None
    parts = []
    for row in failures[:5]:
        hook = row.get("hook") or ""
        script = row.get("script") or ""
        outcome = row.get("outcome") or ""
        code = row.get("exit_code")
        stderr = first_stderr_line(row)
        suffix = f": {stderr}" if stderr else ""
        parts.append(f"{hook}/{script} {outcome} (exit {code}){suffix}")
    if len(failures) > 5:
        parts.append(f"and {len(failures) - 5} more")
    return (
        f"hook-health: {len(failures)} hook run(s) failed since the last prompt: "
        f"{'; '.join(parts)} -- run python3 ~/.claude/hooks/_runner/report.py for the table."
    )


def unreadable_notice(path: str, error: str) -> str:
    return (
        f"hook-health: could not read the hook metrics log {path}: {error}; "
        "hook failures are unchecked this turn."
    )


def failed_rows(rows: list[dict], harness: str) -> list[dict]:
    return [
        row
        for row in rows
        if row.get("harness") == harness
        and row.get("outcome") in FAILURES
        and row.get("hook") != "hook-health"
    ]


def detect(event: dict[str, object], harness: str = "") -> list[Finding]:
    active_harness = harness or _event_harness(event)
    root = metrics_dir()
    log = root / "runs.jsonl"
    state = cursor_path(root, active_harness, session_id(event))
    offset = read_offset(state)
    rows, new_offset, error = read_rows_from(log, offset)
    if error is not None:
        text = unreadable_notice(str(log), error)
        return [Finding(RULE_UNREADABLE_LOG, str(log), text, error)]
    if new_offset != offset:
        write_offset(state, new_offset)
    failures = failed_rows(rows, active_harness)
    text = notice(rows, active_harness)
    if text is None:
        return []
    evidence = _failure_evidence(failures)
    return [
        Finding(
            RULE_FAILED_RUN,
            _failure_subject(evidence),
            text,
            evidence,
        )
    ]


def metrics_dir() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root)


def session_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    value = payload.get("session_id")
    if value is None:
        value = payload.get("conversation_id")
    if value is None:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))[:160] or "unknown"


def cursor_path(root: Path, harness: str, session: str) -> Path:
    return root / f"hook-health-{harness}-{session}.json"


def read_offset(path: Path) -> int:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0
    offset = data.get("offset") if isinstance(data, dict) else None
    if isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0:
        return offset
    return 0


def write_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"offset": offset}, handle, sort_keys=True)
        handle.write("\n")


def read_rows_from(path: Path, offset: int) -> tuple[list[dict[str, Any]], int, str | None]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return [], offset, None
    except OSError as exc:
        return [], offset, str(exc)
    if offset > size:
        offset = 0
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
            end = handle.tell()
    except OSError as exc:
        return [], offset, str(exc)
    rows = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, end, None


def _event_harness(event: dict[str, object]) -> str:
    value = event.get("hook_health_harness")
    if isinstance(value, str):
        return value
    value = event.get("harness")
    if isinstance(value, str):
        return value
    return ""


def _failure_evidence(rows: list[dict]) -> str:
    return json.dumps(
        [
            {
                "harness": row.get("harness"),
                "hook": row.get("hook"),
                "script": row.get("script"),
                "outcome": row.get("outcome"),
                "exit_code": row.get("exit_code"),
                "stderr": first_stderr_line(row),
            }
            for row in rows
        ],
        sort_keys=True,
    )


def _failure_subject(evidence: str) -> str:
    return "runs:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
