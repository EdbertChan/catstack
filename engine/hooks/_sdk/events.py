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
from invoker_id import invoker_sha, invoker_version
from posthog import publish_rows
from source_repo import source_sha
from transcripts import (
    is_publishable_model,
    names_unpublishable_model,
    resolve_model,
    session_id_from_event,
    unresolved_model_reason,
)

SCHEMA = "catstack.hook_event.v1"
CATSTACK_SHA = source_sha(__file__)
INVOKER_VERSION = invoker_version()
INVOKER_SHA = invoker_sha()
DEFAULT_METRICS_DIR = Path.home() / ".cache" / "catstack-hook-metrics"
DEFAULT_REMINDER_STATE_DIR = Path.home() / ".cache" / "catstack-hook-reminders"
REMINDER_STATE_DIR_ENV = "CATSTACK_HOOK_REMINDER_STATE_DIR"
NON_HUMAN_PROMPT_PREFIXES = ("<task-notification", "<local-command", "<system")
PENDING_MODEL_DIR = "pending-model"
DEFERRED_MODEL_SOURCE = "deferred-first-turn"

_session_id = session_id_from_event


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
    effective_level: str = "",
    downgrade_reason: str = "",
) -> list[dict[str, object]]:
    err = stderr if stderr is not None else sys.stderr
    if finding_id is not None and len(findings) != 1:
        raise ValueError("an explicit finding_id requires exactly one finding")
    rows = _rows(
        hook,
        harness,
        event,
        findings,
        mode,
        mode_source,
        duration_ms,
        action,
        finding_id,
        effective_level,
        downgrade_reason,
    )
    return rows if _append_rows(hook, rows, err, event, harness) else []


def write_followup_events(
    hook: str,
    harness: str,
    event: dict[str, object],
    closures: list[Mapping[str, object]],
    stderr: TextIO | None = None,
) -> None:
    err = stderr if stderr is not None else sys.stderr
    rows = [_followup_row(hook, harness, event, closure) for closure in closures]
    _append_rows(hook, rows, err, event, harness)


def is_human_text(text: str) -> bool:
    return not text.lstrip().startswith(NON_HUMAN_PROMPT_PREFIXES)


def is_human_prompt(event: dict[str, object]) -> bool:
    return is_human_text(_prompt_text(event))


def once_per_session_or_compaction(hook: str, event: dict[str, object]) -> bool:
    transcript_path = str(event.get("transcript_path") or event.get("transcriptPath") or "")
    compactions = _compaction_count(transcript_path)
    path = _reminder_state_path(hook, session_id_from_event(event))
    seen = _read_compactions_seen(path)
    if seen is not None and compactions <= seen:
        return False
    _write_compactions_seen(path, compactions)
    return True


def write_stage_event(
    hook: str,
    harness: str,
    session_id: str,
    action: str,
    reason: str,
    finding_id: str | None = None,
    stderr: TextIO | None = None,
    fields: Mapping[str, object] | None = None,
    event: Mapping[str, object] | None = None,
) -> bool:
    err = stderr if stderr is not None else sys.stderr
    if not isinstance(event, Mapping):
        print(
            f"catstack-hook-error {hook}: stage event requires identity payload (event=)",
            file=err,
        )
        return False
    payload: dict[str, object] = dict(event)
    if session_id and not payload.get("session_id") and not payload.get("sessionId") and not payload.get("session"):
        payload["session_id"] = session_id
    row = _row(hook, harness, payload, None, "", "stage", action, 0, finding_id)
    row.update(fields or {})
    row["reason"] = reason
    return _append_rows(hook, [row], err, payload, harness)


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
        for path in (root / PENDING_MODEL_DIR).glob("*"):
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date() < cutoff:
                path.unlink()
    except OSError as exc:
        print(f"catstack-hook-error metrics: event prune failed: {type(exc).__name__}: {exc}", file=err)


def _append_rows(
    hook: str,
    rows: list[dict[str, object]],
    err: TextIO,
    event: Mapping[str, object] | None = None,
    harness: str = "",
) -> bool:
    if not rows:
        return False
    if all(is_publishable_model(row.get("model")) for row in rows):
        _flush_pending_rows(hook, rows[0], err)
        return _write_rows(hook, rows, err)
    if event is None or names_unpublishable_model(event):
        print(
            f"catstack-hook-error {hook}: event write rejected blank or synthetic model",
            file=err,
        )
        return False
    session_id = str(rows[0].get("session_id") or "")
    if not session_id:
        print(
            f"catstack-hook-error {hook}: event write rejected: model unresolved and no session id to hold it under",
            file=err,
        )
        return False
    return _hold_rows(hook, rows, session_id, unresolved_model_reason(event, harness), err)


def _hold_rows(hook: str, rows: list[dict[str, object]], session_id: str, reason: str, err: TextIO) -> bool:
    path = _pending_model_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps({**row, "model_unresolved_reason": reason}, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"catstack-hook-error {hook}: pending model write failed: {type(exc).__name__}: {exc}", file=err)
        return False
    if _claim_once(path.with_suffix(".noted")):
        print(
            f"catstack-hook-note {hook}: model unresolved ({reason}); "
            f"holding rows in {path} until a later event in this session names a model",
            file=err,
        )
    return True


def _flush_pending_rows(hook: str, resolved: Mapping[str, object], err: TextIO) -> None:
    session_id = str(resolved.get("session_id") or "")
    if not session_id:
        return
    path = _pending_model_path(session_id)
    if not path.exists():
        return
    claimed = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.flushing")
    try:
        os.rename(path, claimed)
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"catstack-hook-error {hook}: pending model claim failed: {type(exc).__name__}: {exc}", file=err)
        return
    try:
        lines = claimed.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"catstack-hook-error {hook}: pending model read failed: {type(exc).__name__}: {exc}", file=err)
        return
    rows: list[dict[str, object]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            print(f"catstack-hook-error {hook}: pending model row unreadable, dropped: {line[:80]!r}", file=err)
            continue
        row["model"] = resolved["model"]
        row["model_source"] = DEFERRED_MODEL_SOURCE
        rows.append(row)
    if rows and not _write_rows(hook, rows, err):
        return
    for leftover in (claimed, path.with_suffix(".noted")):
        try:
            leftover.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"catstack-hook-error {hook}: pending model cleanup failed: {type(exc).__name__}: {exc}", file=err)


def _claim_once(marker: Path) -> bool:
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    except OSError:
        return True
    return True


def _pending_model_path(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return _metrics_dir() / PENDING_MODEL_DIR / f"{digest}.jsonl"


def _write_rows(hook: str, rows: list[dict[str, object]], err: TextIO) -> bool:
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
        publish_rows(rows)
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
    effective_level: str = "",
    downgrade_reason: str = "",
) -> list[dict[str, object]]:
    if action is not None:
        rows_action = action
    else:
        rows_action = _action(mode)
    if not findings:
        return [
            _row(
                hook,
                harness,
                event,
                None,
                mode,
                mode_source,
                action or "silent",
                duration_ms,
                finding_id,
                effective_level,
                downgrade_reason,
            )
        ]
    return [
        _row(
            hook,
            harness,
            event,
            finding,
            mode,
            mode_source,
            rows_action,
            duration_ms,
            finding_id,
            effective_level,
            downgrade_reason,
        )
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
    effective_level: str = "",
    downgrade_reason: str = "",
) -> dict[str, object]:
    subject = finding.subject if finding is not None else ""
    model = resolve_model(event, harness) or _test_model_fixture()
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "machine": socket.gethostname(),
        "harness": harness,
        "session_id": session_id_from_event(event),
        "model": model,
        "catstack_sha": CATSTACK_SHA,
        "invoker_version": INVOKER_VERSION,
        "invoker_sha": INVOKER_SHA,
        "hook": hook,
        "rule_id": finding.rule_id if finding is not None else "",
        "subject_hash": _subject_hash(subject),
        "mode": mode,
        "mode_source": mode_source,
        "effective_level": effective_level,
        "downgrade_reason": downgrade_reason,
        "action": action,
        "finding_id": finding_id or uuid.uuid4().hex,
        "duration_ms": duration_ms,
    }


def _test_model_fixture() -> str:
    model = os.environ.get("CATSTACK_HOOK_TEST_MODEL")
    if is_publishable_model(model):
        return model.strip()
    return ""


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
        "session_id": session_id_from_event(event),
        "model": resolve_model(event, harness),
        "catstack_sha": CATSTACK_SHA,
        "invoker_version": INVOKER_VERSION,
        "invoker_sha": INVOKER_SHA,
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


def _prompt_text(event: dict[str, object]) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _reminder_state_dir() -> Path:
    return Path(os.environ.get(REMINDER_STATE_DIR_ENV, DEFAULT_REMINDER_STATE_DIR))


def _reminder_state_path(hook: str, session_id: str) -> Path:
    digest = hashlib.sha256(f"{hook}:{session_id or 'no-session'}".encode("utf-8")).hexdigest()[:16]
    return _reminder_state_dir() / f"{digest}.json"


def _compaction_count(transcript_path: str) -> int:
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0
    count = 0
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("isCompactSummary"):
                    count += 1
    except OSError:
        return 0
    return count


def _read_compactions_seen(path: Path) -> int | None:
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    seen = state.get("compactions_seen") if isinstance(state, dict) else None
    return seen if isinstance(seen, int) else None


def _write_compactions_seen(path: Path, compactions: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump({"compactions_seen": compactions}, handle)
    except OSError:
        pass
