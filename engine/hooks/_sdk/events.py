from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, TextIO

from finding import Finding

SCHEMA = "catstack.hook_event.v1"
DEFAULT_METRICS_DIR = Path.home() / ".cache" / "catstack-hook-metrics"
DEFAULT_REMINDER_STATE_DIR = Path.home() / ".cache" / "catstack-hook-reminders"

NON_HUMAN_PROMPT_PREFIXES = (
    "stop hook feedback:",
    "<task-notification>",
    "base directory for this skill:",
    "this session is being continued",
    "caveat:",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "[request interrupted",
    "another claude session sent a message",
    "<teammate-message",
    "<system-reminder>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<user-prompt-submit-hook>",
    "[image",
)


def write_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
    stderr: TextIO | None = None,
    action: str | None = None,
    finding_id: str | None = None,
) -> list[dict[str, object]]:
    err = stderr if stderr is not None else sys.stderr
    if finding_id is not None and len(findings) != 1:
        raise ValueError("an explicit finding_id requires exactly one finding")
    rows = _rows(hook, harness, event, findings, mode, mode_source, duration_ms, action, finding_id)
    return rows if _append_rows(hook, rows, err) else []


def write_followup_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    closures: list[Mapping[str, object]],
    stderr: TextIO | None = None,
) -> None:
    err = stderr if stderr is not None else sys.stderr
    rows = [_followup_row(hook, harness, event, closure) for closure in closures]
    _append_rows(hook, rows, err)


def prune_old_event_files(days: int = 30, stderr: TextIO | None = None) -> None:
    err = stderr if stderr is not None else sys.stderr
    root = _metrics_dir()
    today = datetime.now(timezone.utc).date()
    marker = root / f".events-pruned-{today.isoformat()}"
    if marker.exists():
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        cutoff = today - timedelta(days=days)
        for path in root.glob("events-*.jsonl"):
            file_date = _event_file_date(path)
            if file_date is not None and file_date < cutoff:
                path.unlink()
    except OSError as exc:
        print(f"catstack-hook-error metrics: event prune failed: {type(exc).__name__}: {exc}", file=err)


def prompt_text(event: Mapping[str, object]) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = event.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return ""


def is_human_prompt(event: Mapping[str, object]) -> bool:
    stripped = prompt_text(event).strip()
    if not stripped:
        return True
    return not stripped.lower().startswith(NON_HUMAN_PROMPT_PREFIXES)


def _reminder_state_dir() -> Path:
    return Path(os.environ.get("CATSTACK_HOOK_REMINDER_STATE_DIR", DEFAULT_REMINDER_STATE_DIR))


def _reminder_state_path(hook: str, session_id: str) -> Path:
    safe_hook = "".join(c if c.isalnum() or c in "-_" else "_" for c in hook)
    safe_session = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session_id or "no-session"))
    return _reminder_state_dir() / f"{safe_hook}-{safe_session}.json"


def _compaction_count(transcript_path: str, err: TextIO) -> int | None:
    if not transcript_path:
        print("catstack-hook-error reminder: no transcript_path on event, compaction count unchecked", file=err)
        return None
    try:
        count = 0
        with open(transcript_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"catstack-hook-error reminder: {transcript_path} has a non-JSON line, skipping it: {exc}",
                        file=err,
                    )
                    continue
                if isinstance(entry, dict) and entry.get("isCompactSummary"):
                    count += 1
        return count
    except (OSError, UnicodeDecodeError) as exc:
        print(f"catstack-hook-error reminder: transcript read failed: {type(exc).__name__}: {exc}", file=err)
        return None


def should_inject_reminder(hook: str, event: Mapping[str, object], stderr: TextIO | None = None) -> bool:
    if not is_human_prompt(event):
        return False
    err = stderr if stderr is not None else sys.stderr
    session_id = _session_id(dict(event))
    transcript_path = str(event.get("transcript_path") or event.get("transcriptPath") or "")
    compactions_now = _compaction_count(transcript_path, err)
    path = _reminder_state_path(hook, session_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = None
    if isinstance(state, dict):
        last_compactions = state.get("compactions")
        if compactions_now is None or not isinstance(last_compactions, int) or compactions_now <= last_compactions:
            return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"compactions": compactions_now if compactions_now is not None else 0}),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"catstack-hook-error reminder: state write failed: {type(exc).__name__}: {exc}", file=err)
    return True


def _append_rows(hook: str, rows: list[dict[str, object]], err: TextIO) -> bool:
    path = _metrics_dir() / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"catstack-hook-error {hook}: event write failed: {type(exc).__name__}: {exc}", file=err)
        return False
    else:
        prune_old_event_files(stderr=err)
        return True


def _rows(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    mode: str,
    mode_source: str,
    duration_ms: int,
    action: str | None,
    finding_id: str | None,
) -> list[dict[str, object]]:
    if action is not None:
        rows_action = action
    else:
        rows_action = _action(mode)
    if not findings:
        return [_row(hook, harness, event, None, mode, mode_source, action or "silent", duration_ms, finding_id)]
    return [
        _row(hook, harness, event, finding, mode, mode_source, rows_action, duration_ms, finding_id)
        for finding in findings
    ]


def _row(
    hook: str,
    harness: str,
    event: dict[str, object],
    finding: Finding | None,
    mode: str,
    mode_source: str,
    action: str,
    duration_ms: int,
    finding_id: str | None,
) -> dict[str, object]:
    subject = finding.subject if finding is not None else ""
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": hook,
        "rule_id": finding.rule_id if finding is not None else "",
        "subject_hash": _subject_hash(subject),
        "mode": mode,
        "mode_source": mode_source,
        "action": action,
        "finding_id": finding_id or uuid.uuid4().hex,
        "duration_ms": duration_ms,
    }


def _followup_row(
    hook: str,
    harness: str,
    event: dict[str, object],
    closure: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": _session_id(event),
        "hook": str(closure.get("hook", hook)),
        "rule_id": str(closure.get("rule_id", "")),
        "subject_hash": str(closure.get("subject_hash", "")),
        "mode": str(closure.get("mode", "")),
        "mode_source": str(closure.get("mode_source", "")),
        "action": "followup",
        "finding_id": str(closure.get("finding_id", "")),
        "duration_ms": 0,
        "outcome": str(closure.get("outcome", "")),
    }


def _session_id(event: dict[str, object]) -> str:
    for key in ("session_id", "sessionId", "session"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _action(mode: str) -> str:
    if mode == "stop":
        return "stopped"
    if mode == "warn":
        return "warned"
    return "silent"


def _metrics_dir() -> Path:
    return Path(os.environ.get("CATSTACK_HOOK_METRICS_DIR", DEFAULT_METRICS_DIR))


def _event_file_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem.removeprefix("events-"))
    except ValueError:
        return None
