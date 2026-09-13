from __future__ import annotations

FAILURES = {"crashed", "timed_out", "caught_error"}


def first_stderr_line(row: dict) -> str:
    tail = row.get("stderr_tail")
    if not isinstance(tail, str):
        return ""
    for line in tail.splitlines():
        if line.strip():
            return line.strip()
    return ""


def notice(rows: list[dict], harness: str) -> str | None:
    failures = [
        row
        for row in rows
        if row.get("harness") == harness
        and row.get("outcome") in FAILURES
        and row.get("hook") != "hook-health"
    ]
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
