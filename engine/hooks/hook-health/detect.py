from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402

FAILURES = {"crashed", "timed_out", "caught_error"}
STALE_SCAN_SECONDS = 120

RULE_FAILED_RUNS = "hook-health.failed-runs"
RULE_UNREADABLE_LOG = "hook-health.unreadable-log"
RULE_SCAN_FAILED = "hook-health.scan-failed"


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
    blocked = sum(
        1
        for row in rows
        if row.get("harness") == harness and row.get("hook") != "hook-health" and row.get("outcome") == "blocked"
    )
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
    text = (
        f"hook-health: {len(failed)} hook run(s) failed since the last prompt: "
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


def detect(event: dict[str, object]) -> list[Finding]:
    harness = _harness(event)
    root = metrics_dir()
    root.mkdir(parents=True, exist_ok=True)
    session = session_id(event)
    texts = take_notices(notice_dir(root, harness, session))
    state = cursor_path(root, harness, session)
    if not state.exists():
        write_offset(state, log_size(root / "runs.jsonl"))
        return [_finding_for_notice(text) for text in texts]
    start_scan(root, harness, session)
    return [_finding_for_notice(text) for text in texts]


def _harness(event: dict[str, object]) -> str:
    value = event.get("_catstack_harness")
    if isinstance(value, str) and value:
        return value
    value = event.get("harness")
    if isinstance(value, str) and value:
        return value
    return "claude"


def _finding_for_notice(text: str) -> Finding:
    if "could not read the hook metrics log" in text:
        rule_id = RULE_UNREADABLE_LOG
    elif "background scan of the hook metrics log failed" in text:
        rule_id = RULE_SCAN_FAILED
    else:
        rule_id = RULE_FAILED_RUNS
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Finding(
        rule_id=rule_id,
        subject=f"notice:{digest}",
        message=text,
        evidence=text,
    )


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


def read_state(path: Path) -> tuple[int, frozenset[str]]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0, frozenset()
    if not isinstance(data, dict):
        return 0, frozenset()
    offset = data.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        offset = 0
    seen = data.get("seen")
    if not isinstance(seen, list):
        seen = []
    return offset, frozenset(item for item in seen if isinstance(item, str))


def write_offset(path: Path, offset: int, seen: frozenset[str] = frozenset()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"offset": offset, "seen": sorted(seen)}, handle, sort_keys=True)
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


def lock_path(root: Path, harness: str, session: str) -> Path:
    return root / f"hook-health-{harness}-{session}.scanning"


def notice_dir(root: Path, harness: str, session: str) -> Path:
    return root / "hook-health-notices" / f"{harness}-{session}"


def log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def take_notices(folder: Path) -> list[str]:
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return []
    texts = []
    for name in names:
        path = folder / name
        texts.append(path.read_text(encoding="utf-8").strip())
        path.unlink()
    return [text for text in texts if text]


def add_notice(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{os.getpid()}.txt"
    tmp = folder / f".{name}"
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, folder / name)


def claim_lock(path: Path) -> bool:
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < STALE_SCAN_SECONDS:
                return False
            sys.stderr.write(f"catstack-hook-error hook-health: removing scan lock {path} left {age:.0f}s ago\n")
            path.unlink(missing_ok=True)
            continue
        os.close(fd)
        return True
    return False


def start_scan(root: Path, harness: str, session: str) -> None:
    lock = lock_path(root, harness, session)
    if not claim_lock(lock):
        return
    try:
        with (root / "hook-health-scan.log").open("a", encoding="utf-8") as errors:
            subprocess.Popen(
                [sys.executable or "python3", os.path.abspath(__file__), "scan", harness, session],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=errors,
            )
    except BaseException:
        lock.unlink(missing_ok=True)
        raise


def scan(harness: str, session: str) -> None:
    root = metrics_dir()
    log = root / "runs.jsonl"
    state = cursor_path(root, harness, session)
    try:
        offset, seen = read_state(state)
        rows, new_offset, error = read_rows_from(log, offset)
        if error is not None:
            text = unreadable_notice(str(log), error)
        else:
            fresh = frozenset(signature(row) for row in failures(rows, harness, seen))
            if new_offset != offset or fresh:
                write_offset(state, new_offset, seen | fresh)
            text = notice(rows, harness, seen)
    except Exception as exc:
        sys.stderr.write(f"catstack-hook-error hook-health: scan {harness}-{session}: {type(exc).__name__}: {exc}\n")
        text = scan_failed_notice(f"{type(exc).__name__}: {exc}")
    try:
        if text is not None:
            add_notice(notice_dir(root, harness, session), text)
    finally:
        lock_path(root, harness, session).unlink(missing_ok=True)


if __name__ == "__main__" and sys.argv[1:2] == ["scan"] and len(sys.argv) == 4:
    scan(sys.argv[2], sys.argv[3])
