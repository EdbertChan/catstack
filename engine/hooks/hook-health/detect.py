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
    watched = [row for row in rows if row.get("harness") == harness and row.get("hook") != "hook-health"]
    failures = [row for row in watched if row.get("outcome") in FAILURES]
    blocked = sum(1 for row in watched if row.get("outcome") == "blocked")
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
    text = (
        f"hook-health: {len(failures)} hook run(s) failed since the last prompt: "
        f"{'; '.join(parts)} -- run python3 ~/.claude/hooks/_runner/report.py for the table."
    )
    if blocked:
        text += (
            f"\nhook-health: {blocked} hook run(s) blocked on purpose "
            "(a stop-mode hook doing its job, not a hook error)."
        )
    return text


def unreadable_notice(path: str, error: str) -> str:
    return (
        f"hook-health: could not read the hook metrics log {path}: {error}; "
        "hook failures are unchecked this turn."
    )


def scan_failed_notice(error: str) -> str:
    return f"hook-health: the background scan of the hook metrics log failed: {error}; hook failures are unchecked this turn."
