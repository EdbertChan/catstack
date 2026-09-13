#!/usr/bin/env python3
"""A well-formed CAT-UNVERIFIED tag is a deferral, not a discharge.

Every other evidence hook treats `markers.well_formed_tags(message)` as
equivalent to evidence and goes silent (see prove-it-ship-gate/detect.py).
cat-mode/SKILL.md:269 says the opposite: "Any hedge auto-runs prove-it in the
same turn -- a hedge is a trigger to verify, never a place to stop." Nothing
reconciled the two, so a correctly-formed tag was a free, unlogged exit.

This module does not re-block the turn that emits a tag; blocking there
deadlocks, because the tag exists precisely for checks that cannot run now.
It records the tag against the session and surfaces it on the next prompt,
which is the earliest point a reminder can change behaviour without
preventing the turn from ending at all.

A tag is discharged when a later turn runs a verification tool and stops
re-emitting it. Turn count since first sight is kept so a tag that survives
many turns can be escalated rather than quietly accumulating.
"""
from __future__ import annotations

import json
import functools
import importlib.util
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))

import markers  # noqa: E402

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "NotebookRead"}
ESCALATE_AFTER_TURNS = 3
MAX_LISTED = 5
EXCERPT_LIMIT = 3000

CLAIM_RE = re.compile(
    r"\{\{\s*CAT-UNVERIFIED\s*:?\s*(?P<claim>.*?)(?:--|—)\s*cannot\s+verify\s*:\s*(?P<reason>[^}]*)\}\}",
    re.IGNORECASE | re.DOTALL,
)


def ledger_dir() -> str:
    base = os.environ.get("CATSTACK_TAG_LEDGER_DIR")
    if base:
        return base
    return os.path.join(os.path.expanduser("~"), ".cache", "catstack-unverified-ledger")


def ledger_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return os.path.join(ledger_dir(), f"{safe}.jsonl")


def parse_tags(message: str) -> list[dict]:
    """Well-formed tags only, split into claim and reason."""
    out = []
    for raw in markers.well_formed_tags(message or ""):
        match = CLAIM_RE.search(raw)
        if not match:
            continue
        claim = " ".join(match.group("claim").split())
        reason = " ".join(match.group("reason").split())
        if claim and reason:
            out.append({"claim": claim, "reason": reason, "tag": raw})
    return out


def read_ledger(session_id: str) -> list[dict]:
    path = ledger_path(session_id)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                sys.stderr.write(
                    f"unverified-tag-ledger: {path}:{number} is not JSON, skipping row: {exc}\n")
    return rows


def write_ledger(session_id: str, rows: list[dict]) -> None:
    path = ledger_path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def outstanding(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not row.get("resolved")]


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_transcript_tail(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()[-EXCERPT_LIMIT:]
    except OSError:
        return ""


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def transcript_excerpt(payload: dict) -> str:
    value = payload.get("transcript")
    if isinstance(value, str):
        if os.path.isfile(value):
            return _read_transcript_tail(value)
        return value[-EXCERPT_LIMIT:]
    if isinstance(value, list):
        parts = []
        for entry in value:
            if isinstance(entry, dict):
                role = entry.get("role") or entry.get("type") or "entry"
                text = _content_text(entry.get("content") or entry.get("message"))
                if text:
                    parts.append(f"{role}: {text}")
        return "\n".join(parts)[-EXCERPT_LIMIT:]
    for key in ("agent_transcript_path", "transcript_path", "transcriptPath"):
        path = payload.get(key)
        if isinstance(path, str):
            text = _read_transcript_tail(path)
            if text:
                return text
    return _last_assistant_text(payload)[-EXCERPT_LIMIT:]


def blocker_judge_text(tag: dict, excerpt: str) -> str:
    return "\n".join([
        f"TAG: {tag.get('tag') or ''}",
        f"CLAIM: {tag.get('claim') or ''}",
        f"BLOCKER: {tag.get('reason') or ''}",
        "TRANSCRIPT EXCERPT:",
        excerpt or "",
    ])


def enqueue_blocker_judge(session_id: str, tag: dict, excerpt: str) -> dict:
    dictionary = _phrases().load("tag-blocker-removable")
    job = _phrases().job(dictionary, ledger_path(session_id), blocker_judge_text(tag, excerpt))
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is None:
        return {"blocker_judge_id": None, "blocker_judge_outcome": "unchecked", "blocker_judge_reason": "judge did not enqueue"}
    return {"blocker_judge_id": job_id, "blocker_judge_outcome": "pending"}


def try_enqueue_blocker_judge(session_id: str, tag: dict, excerpt: str) -> dict:
    try:
        return enqueue_blocker_judge(session_id, tag, excerpt)
    except Exception as exc:
        sys.stderr.write(
            f"unverified-tag-ledger: blocker judge enqueue error, continuing unchecked: {type(exc).__name__}: {exc}\n")
        return {"blocker_judge_id": None, "blocker_judge_outcome": "unchecked", "blocker_judge_reason": str(exc)}


def apply_blocker_verdicts(session_id: str, rows: list[dict]) -> bool:
    by_id = {row.get("blocker_judge_id"): row for row in rows if row.get("blocker_judge_id")}
    if not by_id:
        return False
    changed = False
    try:
        verdicts = _judge().drain(ledger_path(session_id))
    except Exception as exc:
        sys.stderr.write(
            f"unverified-tag-ledger: blocker judge drain error, continuing unchecked: {type(exc).__name__}: {exc}\n")
        for row in by_id.values():
            if row.get("blocker_judge_outcome") == "pending":
                row["blocker_judge_outcome"] = "unchecked"
                row["blocker_judge_reason"] = str(exc)
                changed = True
        return changed
    for verdict in verdicts:
        row = by_id.get(verdict.get("id"))
        if row is None:
            continue
        outcome = verdict.get("outcome")
        row["blocker_judge_outcome"] = outcome if outcome in {"hit", "clean", "unchecked"} else "unchecked"
        row["blocker_judge_reason"] = str(verdict.get("reason") or "")
        changed = True
    return changed


def record_turn(session_id: str, message: str, tools_used: set[str], now=None, transcript_excerpt_text: str = "") -> list[dict]:
    """Log new tags, discharge ones this turn verified and dropped."""
    stamp = now() if now else time.time()
    rows = read_ledger(session_id)
    tags = parse_tags(message)
    present = {tag["claim"] for tag in tags}
    verified = bool(tools_used & VERIFY_TOOLS)
    apply_blocker_verdicts(session_id, rows)

    for row in rows:
        if row.get("resolved"):
            continue
        if row["claim"] in present:
            row["turns"] = row.get("turns", 0) + 1
        elif verified:
            row["resolved"] = True
            row["resolved_at"] = stamp
        else:
            row["turns"] = row.get("turns", 0) + 1

    known = {row["claim"] for row in rows}
    for tag in tags:
        if tag["claim"] in known:
            continue
        row = {
            "claim": tag["claim"],
            "reason": tag["reason"],
            "first_seen": stamp,
            "turns": 0,
            "resolved": False,
        }
        row.update(try_enqueue_blocker_judge(session_id, tag, transcript_excerpt_text))
        rows.append(row)

    write_ledger(session_id, rows)
    return rows


def row_detail(row: dict) -> str:
    parts = [f"blocked on: {row['reason']}", f"{row.get('turns', 0)} turn(s) old"]
    outcome = row.get("blocker_judge_outcome")
    if outcome == "hit":
        parts.append("clearable blocker: open claim to verify")
    elif outcome == "unchecked":
        reason = str(row.get("blocker_judge_reason") or "no judge result")
        parts.append(f"blocker judge unchecked: {reason}")
    return "; ".join(parts)


def reminder(session_id: str, payload: dict | None = None) -> str:
    """Text for UserPromptSubmit, or empty when nothing is outstanding."""
    rows = read_ledger(session_id)
    if apply_blocker_verdicts(session_id, rows):
        write_ledger(session_id, rows)
    open_rows = outstanding(rows)
    if not open_rows:
        return ""
    stale = [row for row in open_rows if row.get("turns", 0) >= ESCALATE_AFTER_TURNS]
    lines = [
        "unverified-tag-ledger: "
        f"{len(open_rows)} CAT-UNVERIFIED claim(s) from earlier turns are still unverified.",
        "cat-mode/SKILL.md:269 -- a hedge is a trigger to verify, never a place to stop. "
        "The tag deferred these; it did not settle them.",
    ]
    for row in open_rows[:MAX_LISTED]:
        lines.append(f"  - {row['claim']}  ({row_detail(row)})")
    if len(open_rows) > MAX_LISTED:
        lines.append(f"  ... and {len(open_rows) - MAX_LISTED} more")
    lines.append(
        "For each: run the check now and paste its output, or say plainly that it is still blocked and why. "
        "The user can retire one by saying to drop it.")
    if stale:
        lines.append(
            f"{len(stale)} of these are {ESCALATE_AFTER_TURNS}+ turns old -- that is a reflect trigger, "
            "not a backlog item.")
    return "\n".join(lines)


def evaluate(payload: dict) -> dict:
    """Record the turn, then decide whether it may end.

    A tag earns its place only after an attempt. cat-mode/SKILL.md:269 asks for
    a verify in the SAME turn, so a tag emitted by a turn that ran no
    verification tool is a claim nobody tried to check, and that turn is
    refused. Requiring an attempt is not requiring success: run the check, and
    if it cannot run or comes back inconclusive, the tag is then honest.

    `stop_hook_active` releases the block so the rewrite turn can finish --
    without it the refusal loops forever, because a reply being rewritten to
    satisfy this hook has no tool call of its own either.
    """
    session_id = str(payload.get("session_id") or "")
    message = _last_assistant_text(payload)
    tools = _tools_used(payload)
    rows = record_turn(session_id, message, tools, transcript_excerpt_text=transcript_excerpt(payload))

    new_claims = {tag["claim"] for tag in parse_tags(message)}
    if not new_claims:
        return {"note": "", "block": ""}

    if not tools & VERIFY_TOOLS and not payload.get("stop_hook_active"):
        claims = "; ".join(sorted(new_claims)[:MAX_LISTED])
        return {"note": "", "block": (
            "unverified-tag-ledger: this turn tags a claim as unverified but ran no "
            f"verification tool. Untried claim(s): {claims}. "
            "cat-mode/SKILL.md:269 -- a hedge is a trigger to verify, never a place to stop. "
            "Run the check now (Bash/Read/Grep/Glob) and paste its output. The tag is for a "
            "check that was attempted and could not settle the claim, not for one nobody ran.")}

    fresh = [row for row in rows
             if row["claim"] in new_claims and not row.get("resolved") and row.get("turns", 0) == 0]
    if not fresh:
        return {"note": "", "block": ""}
    return {"note": (
        f"unverified-tag-ledger: logged {len(fresh)} CAT-UNVERIFIED claim(s) against this session. "
        "They are deferred, not discharged, and will be raised again next turn "
        "(cat-mode/SKILL.md:269)."), "block": ""}


def decide_stop(payload: dict) -> str:
    return evaluate(payload)["note"]


def _last_assistant_text(payload: dict) -> str:
    for key in ("last_assistant_message", "assistant_message", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    transcript = payload.get("transcript") or []
    if isinstance(transcript, list):
        for entry in reversed(transcript):
            if isinstance(entry, dict) and entry.get("role") == "assistant":
                content = entry.get("content")
                if isinstance(content, str):
                    return content
    return ""


def _tools_used(payload: dict) -> set[str]:
    raw = payload.get("tools_used") or payload.get("tool_names") or []
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    return set()
