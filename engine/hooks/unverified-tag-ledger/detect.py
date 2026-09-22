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
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

import flags  # noqa: E402
import markers  # noqa: E402

VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "NotebookRead"}
ESCALATE_AFTER_TURNS = 3
MAX_LISTED = 5

REMINDER_FLAG = "CATSTACK_UNVERIFIED_TAG_REMINDER"
REMINDER_MODES = ("off", "stale", "all")
DEFAULT_REMINDER_MODE = "stale"

DISCHARGE_REFLECT = (
    "unverified-tag-ledger: {count} claim(s) went from unverified to checked this turn: "
    "{claims}. That transition is the whole event: the claim went out first and the check "
    "ran after. No wording has to admit anything for this to be true, which is why the "
    "phrase scanners miss it -- an evidence-order miss carries no wrongness word. "
    "Treat it as a reflect trigger, not a milestone: run reflect on this transcript, or "
    "say plainly why this one does not need it."
)

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
            out.append({"claim": claim, "reason": reason})
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


def record_turn(session_id: str, message: str, tools_used: set[str] | None, now=None) -> list[dict]:
    """Log new tags, discharge ones this turn verified and dropped.

    `tools_used` is None when the turn's tool calls could not be read. That is
    not the same as "ran no tools": an unchecked turn discharges nothing, so a
    row stays outstanding rather than being retired on no evidence.
    """
    stamp = now() if now else time.time()
    rows = read_ledger(session_id)
    present = {tag["claim"] for tag in parse_tags(message)}
    verified = tools_used is not None and bool(tools_used & VERIFY_TOOLS)

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
    for tag in parse_tags(message):
        if tag["claim"] in known:
            continue
        rows.append({
            "claim": tag["claim"],
            "reason": tag["reason"],
            "first_seen": stamp,
            "turns": 0,
            "resolved": False,
        })

    write_ledger(session_id, rows)
    return rows


def reminder_mode(environ=None, cwd=None, home=None) -> tuple[str, str]:
    """(mode, note). mode is off, stale, or all; note names what could not be read.

    Three settings, not two, because the complaint is volume and not the
    ledger. `off` silences the next-prompt reminder and keeps recording rows,
    so the ledger stays minable either way. `stale` -- the default -- reminds
    only about claims that have already survived ESCALATE_AFTER_TURNS turns,
    which is the subset this hook already singles out as a reflect trigger.
    `all` is the older behaviour, every outstanding claim every prompt.

    Unset means `stale`, deliberately. A flag whose unset value is the old
    behaviour changes nothing for the person who asked for less.
    """
    found = flags.resolve_flag(
        REMINDER_FLAG, os.environ if environ is None else environ, cwd, home)
    note = found.unreadable_note(REMINDER_FLAG)
    raw = (found.value or "").strip().lower()
    if raw in REMINDER_MODES:
        return raw, note
    if raw:
        extra = (
            f"unverified-tag-ledger: {REMINDER_FLAG}={found.value!r} is not "
            f"{', '.join(REMINDER_MODES)}; using {DEFAULT_REMINDER_MODE}.")
        note = f"{note}\n{extra}" if note else extra
    return DEFAULT_REMINDER_MODE, note


def reminder(session_id: str, mode: str = DEFAULT_REMINDER_MODE) -> str:
    """Text for UserPromptSubmit, or empty when nothing is due."""
    if mode == "off":
        return ""
    open_rows = outstanding(read_ledger(session_id))
    if mode != "all":
        open_rows = [row for row in open_rows
                     if row.get("turns", 0) >= ESCALATE_AFTER_TURNS]
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
        lines.append(f"  - {row['claim']}  (blocked on: {row['reason']}; {row.get('turns', 0)} turn(s) old)")
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
    tools = tools_used_this_turn(payload)
    was_open = {row["claim"] for row in outstanding(read_ledger(session_id))}
    rows = record_turn(session_id, message, tools)
    notes = []
    discharged = sorted(
        row["claim"] for row in rows if row.get("resolved") and row["claim"] in was_open)
    if discharged:
        notes.append(DISCHARGE_REFLECT.format(
            count=len(discharged), claims="; ".join(discharged[:MAX_LISTED])))

    new_claims = {tag["claim"] for tag in parse_tags(message)}
    if not new_claims:
        return {"note": "\n".join(notes), "block": ""}

    if tools is None:
        notes.append(
            f"unverified-tag-ledger: logged {len(new_claims)} CAT-UNVERIFIED claim(s), but this "
            "turn's tool calls could not be read from transcript_path (see the line above), so "
            "whether a check was attempted is UNCHECKED, not clean. Nothing was discharged and "
            "the turn was not refused.")
        return {"note": "\n".join(notes), "block": ""}

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
    if fresh:
        notes.append(
            f"unverified-tag-ledger: logged {len(fresh)} CAT-UNVERIFIED claim(s) against this "
            "session. They are deferred, not discharged, and will be raised again next turn "
            "(cat-mode/SKILL.md:269).")
    return {"note": "\n".join(notes), "block": ""}


def decide_stop(payload: dict) -> str:
    return evaluate(payload)["note"]


def _last_assistant_text(payload: dict) -> str:
    """The reply this Stop event is about.

    `last_assistant_message` is the key a real Claude Code Stop payload
    carries -- see tests/fixtures/claude-stop-payload.json, captured from a
    live run. The transcript is the fallback for a payload that omits it.
    """
    value = payload.get("last_assistant_message")
    if isinstance(value, str) and value.strip():
        return value
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    text = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and _assistant_text(entry):
                    text = _assistant_text(entry)
    except (OSError, UnicodeError) as exc:
        sys.stderr.write(
            f"unverified-tag-ledger: cannot read transcript {path}: {exc!r}\n")
        return ""
    return text


def _entry_content(entry: dict):
    message = entry.get("message")
    if isinstance(message, dict):
        return str(message.get("role") or ""), message.get("content")
    return str(entry.get("role") or ""), entry.get("content")


def _assistant_text(entry: dict) -> str:
    role, content = _entry_content(entry)
    if entry.get("type") != "assistant" and role != "assistant":
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
    ).strip()


def _tool_names(entry: dict) -> list[str]:
    role, content = _entry_content(entry)
    if entry.get("type") != "assistant" and role != "assistant":
        return []
    if not isinstance(content, list):
        return []
    return [
        str(block.get("name") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _starts_a_new_turn(entry: dict) -> bool:
    """True for a real user prompt -- the boundary this turn's tools start at.

    A `tool_result` arrives as a user entry too, and so does the hook's own
    feedback (`isMeta`). Neither is the user speaking, so neither ends the
    turn whose tool calls we are counting.
    """
    role, content = _entry_content(entry)
    if entry.get("type") != "user" and role != "user":
        return False
    if entry.get("isMeta"):
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def tools_used_this_turn(payload: dict) -> set[str] | None:
    """Tool names this turn actually called, or None when that cannot be read.

    Claude Code's Stop payload has no tool list of any kind -- see the
    captured fixture. The turn's tool calls live in the transcript, which is
    how `scope-lock/detect.py` reads the same thing.

    Three outcomes, not two: a set (checked), an empty set (checked, no tools),
    and None (unchecked). None is not "no tools" -- a caller that collapses it
    to an empty set would block a turn it never managed to inspect, and would
    discharge ledger rows on no evidence.
    """
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        sys.stderr.write(
            "unverified-tag-ledger: payload carries no transcript_path, "
            "this turn's tool list is unchecked\n")
        return None
    names: set[str] = set()
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    sys.stderr.write(
                        f"unverified-tag-ledger: {path} has a non-JSON line, "
                        f"tool list is unchecked: {exc}\n")
                    return None
                if not isinstance(entry, dict):
                    continue
                if _starts_a_new_turn(entry):
                    names = set()
                    continue
                names.update(name for name in _tool_names(entry) if name)
    except (OSError, UnicodeError) as exc:
        sys.stderr.write(
            f"unverified-tag-ledger: cannot read transcript {path}, "
            f"tool list is unchecked: {exc!r}\n")
        return None
    return names
