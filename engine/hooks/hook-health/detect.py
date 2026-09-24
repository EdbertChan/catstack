from __future__ import annotations

import json

FAILURES = {"crashed", "timed_out", "caught_error"}


def first_stderr_line(row: dict) -> str:
    tail = row.get("stderr_tail")
    if not isinstance(tail, str):
        return ""
    for line in tail.splitlines():
        if line.strip():
            return line.strip()
    return ""


def error_line(row: dict) -> str:
    tail = row.get("stderr_tail")
    if isinstance(tail, str) and ("Traceback (most recent call last):" in tail or '  File "' in tail):
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        return lines[-1]
    return first_stderr_line(row)


def signature(row: dict) -> str:
    return json.dumps(
        [row.get("hook"), row.get("script"), row.get("outcome"), row.get("exit_code"), error_line(row)]
    )


def failures(rows: list[dict], harness: str, seen: frozenset[str] = frozenset()) -> list[dict]:
    return [
        row
        for row in rows
        if row.get("harness") == harness
        and row.get("outcome") in FAILURES
        and row.get("hook") != "hook-health"
        and signature(row) not in seen
    ]


def notice(rows: list[dict], harness: str, seen: frozenset[str] = frozenset()) -> str | None:
    failed = failures(rows, harness, seen)
    if not failed:
        return None
    distinct: dict[str, dict] = {}
    for row in failed:
        distinct.setdefault(signature(row), row)
    parts = []
    for row in list(distinct.values())[:5]:
        hook = row.get("hook") or ""
        script = row.get("script") or ""
        outcome = row.get("outcome") or ""
        code = row.get("exit_code")
        stderr = error_line(row)
        suffix = f": {stderr}" if stderr else ""
        parts.append(f"{hook}/{script} {outcome} (exit {code}){suffix}")
    if len(distinct) > 5:
        parts.append(f"and {len(distinct) - 5} more")
    return (
        f"hook-health: {len(failed)} hook run(s) failed since the last prompt: "
        f"{'; '.join(parts)} -- run python3 ~/.claude/hooks/_runner/report.py for the table."
    )


def unreadable_notice(path: str, error: str) -> str:
    return (
        f"hook-health: could not read the hook metrics log {path}: {error}; "
        "hook failures are unchecked this turn."
    )


def scan_failed_notice(error: str) -> str:
    return f"hook-health: the background scan of the hook metrics log failed: {error}; hook failures are unchecked this turn."
