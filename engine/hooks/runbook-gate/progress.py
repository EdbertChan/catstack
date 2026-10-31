"""The session's runbook progress note: where the playbook got to, and the proof or reason per step.

One JSON file per session under ``~/.cache/catstack-runbook`` (or
``CATSTACK_RUNBOOK_STATE_DIR``). The gate writes it on every Stop it measures
and reads it back on the next one, so a step whose proof has aged out of the
transcript -- a compaction drops the tool result that proved it -- keeps the
status it already earned.

Reading has three outcomes, not two: a note, no note at all, and a note that
could not be read. The third is reported to the caller rather than returned as
an empty note, because losing a remembered override makes the gate block where
it should not, and that has to be visible.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

SCHEMA = "catstack.runbook_progress.v1"
STATE_DIR_ENV = "CATSTACK_RUNBOOK_STATE_DIR"
DEFAULT_STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "catstack-runbook")
STATUS_STRENGTH = {"unknown": 0, "skipped": 1, "overridden": 2, "done": 3}
TTL_SECONDS = 24 * 3600
NO_STEP = 0


def state_dir() -> str:
    """Where this machine keeps its runbook progress notes."""
    return os.environ.get(STATE_DIR_ENV) or DEFAULT_STATE_DIR


def note_path(session_key: str) -> str:
    """The progress note for one session, without creating its directory."""
    if not session_key:
        return ""
    return os.path.join(state_dir(), f"{session_key}.json")


def read_note(path: str) -> tuple[dict[str, Any], str]:
    """One session's progress note, plus the reason it could not be read."""
    if not path:
        return {}, "the stop payload named no session, so no progress note could be read"
    if not os.path.exists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {}, f"{path}: progress note unreadable ({error}); earlier proof for this session is lost"
    if not isinstance(stored, dict):
        return {}, f"{path}: progress note is not an object; earlier proof for this session is lost"
    if time.time() - _updated_at(stored) > TTL_SECONDS:
        return {}, ""
    return stored, ""


def _updated_at(note: dict[str, Any]) -> float:
    """When this note was last written, zero when the stamp is missing or malformed."""
    try:
        return float(note.get("updated_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def stored_steps(note: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Every step row a stored note carries, by step number."""
    rows = note.get("steps")
    if not isinstance(rows, list):
        return {}
    found: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("step"))
        except (TypeError, ValueError):
            continue
        found[number] = row
    return found


def is_stronger(status: str, than: str) -> bool:
    """True when one status is further along the playbook than another."""
    return STATUS_STRENGTH.get(status, 0) > STATUS_STRENGTH.get(than, 0)


def carried_forward(measured: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    """One step row, keeping the stronger of this Stop's status and the one already recorded."""
    if not isinstance(stored, dict):
        return measured
    if not is_stronger(str(stored.get("status", "")), str(measured.get("status", ""))):
        return measured
    carried = dict(measured)
    for field in ("status", "evidence_ref", "reason", "proof"):
        carried[field] = stored.get(field, measured.get(field, ""))
    carried["proof"] = f"{carried['proof']} (carried forward from an earlier stop in this session)"
    return carried


def current_step(steps: list[dict[str, Any]]) -> int:
    """The lowest-numbered step still unknown, or the last step once every one is settled."""
    unsettled = [step for step in steps if str(step.get("status", "")) == "unknown"]
    if unsettled:
        return int(unsettled[0]["step"])
    if not steps:
        return NO_STEP
    return int(steps[-1]["step"])


def build_note(playbook: str, profile: str, source: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The note to store for this session after one Stop."""
    return {
        "schema": SCHEMA,
        "updated_at": time.time(),
        "playbook": playbook,
        "profile": profile,
        "source": source,
        "current_step": current_step(steps),
        "steps": steps,
    }


def write_note(path: str, note: dict[str, Any]) -> str:
    """Store one session's progress note, returning the reason it could not be written."""
    if not path:
        return "the stop payload named no session, so no progress note was written"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(note, handle)
    except OSError as error:
        return f"{path}: progress note unwritable ({error}); the next stop starts from the transcript alone"
    return ""
