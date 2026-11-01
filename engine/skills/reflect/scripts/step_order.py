#!/usr/bin/env python3
"""Per-session step order: the skills, hooks and interventions a session fired, in order.

Usage:
    step_order.py <path-to-claude-session.jsonl> [--metrics-dir DIR] [--out FILE]

A hand-written playbook states an order. This reads the order sessions
actually took, so a later compiler can correct that order instead of trusting
the draft. One row per step, carrying its kind and its id:

    skill         the skill name, from skill-usage-log's skill_used events
    hook          the hook name, for runner rows whose outcome spoke or blocked
    intervention  the kinds token_audit classified the human message as

Each session also gets a task type, matched by the fixed TASK_TYPE_KEYWORDS
table against its first human prompt, and nothing else. The table is ordered
most specific first: the first pattern that matches wins and nothing after it
is consulted. No model is asked.

A missing or unreadable hook metrics directory is reported as unchecked, never
as an empty step list: a session whose hooks nobody recorded is a different
answer from a session that fired none. The same holds for a transcript with no
classifiable human prompt, whose task type stays None.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cluster_interventions
import token_audit
import transcript_provenance

DEFAULT_METRICS_DIR = os.path.join("~", ".cache", "catstack-hook-metrics")
METRICS_DIR_ENV = "CATSTACK_HOOK_METRICS_DIR"
RUNS_FILE_NAME = "runs.jsonl"
EVENTS_FILE_PATTERN = "events-*.jsonl"
SKILL_USAGE_HOOK = "skill-usage-log"
SKILL_USED_ACTION = "skill_used"
SKILL_UNCHECKED_ACTION = "skill_usage_unchecked"
SPEAKING_OUTCOMES = frozenset({"spoke", "blocked"})
SKILL_KIND = "skill"
HOOK_KIND = "hook"
INTERVENTION_KIND = "intervention"
KIND_TIE_ORDER = {INTERVENTION_KIND: 0, SKILL_KIND: 1, HOOK_KIND: 2}
DEFAULT_TASK_TYPE = "other"

TASK_TYPE_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("reflect", re.compile(
        r"(?:^|\s)/(?:reflect|automate-me|thrash)\b"
        r"|\breflect on\b|\bautomate me\b|\bmine (?:the )?sessions?\b",
        re.I,
    )),
    ("land-stack", re.compile(
        r"\bland (?:the |this )?(?:stack|pr|branch)\b|\bland it\b"
        r"|\bmerge queue\b|\bmergify\b|\bgraphite\b"
        r"|\bqueue (?:the |this )?(?:stack|pr)\b|\bpr stack\b|\bstacked prs?\b",
        re.I,
    )),
    ("revert-or-merge", re.compile(
        r"\brevert\b|\broll ?back\b|\brebase\b|\bcherry[- ]pick\b"
        r"|\bmerge conflicts?\b|\bresolve (?:the )?conflicts?\b|\bback ?out\b",
        re.I,
    )),
    ("ship-detector", re.compile(
        r"\bdetectors?\b|\bpre ?tool ?use\b|\bstop hook\b|\bhooks?\b"
        r"|\bgates?\b|\bcheck_[a-z0-9_]+\.py\b|\blinter?\b",
        re.I,
    )),
    ("ui-change", re.compile(
        r"\bui\b|\blayouts?\b|\bscreenshots?\b|\bcss\b|\bbuttons?\b"
        r"|\bvisual proof\b|\bon screen\b|\bthe page\b",
        re.I,
    )),
    ("delegate", re.compile(
        r"\bsubagents?\b|\bdelegate\b|\bfan ?out\b|\bworkflows?\b"
        r"|\bin parallel\b|\bparallel agents?\b|\bspawn\b",
        re.I,
    )),
    ("bugfix", re.compile(
        r"\bbugs?\b|\bfix\b|\bfixe[sd]\b|\bbroken\b|\brepro\w*\b|\bfailing\b"
        r"|\bregressions?\b|\bcrash\w*\b|\bstack trace\b|\bstill fails?\b",
        re.I,
    )),
    ("ship-pr", re.compile(
        r"\bprs?\b|\bpull requests?\b|\bship it\b|\bpublish\b|\bopen it\b",
        re.I,
    )),
]


def metrics_directory(override: str | None = None) -> str:
    """Where the hook runner writes runs.jsonl and its stage events."""
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(os.environ.get(METRICS_DIR_ENV) or DEFAULT_METRICS_DIR)


def _read_rows(path: str) -> tuple[list[dict[str, Any]] | None, int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return [], 0
    except OSError as exc:
        print(f"UNCHECKED: {path} unreadable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None, 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return rows, malformed


def _rotated_run_paths(runs_path: str) -> list[str]:
    """Oldest rotation first, so reading in file order reads in time order."""
    prefix = runs_path + "."
    indexed = []
    for candidate in glob.glob(prefix + "*"):
        suffix = candidate[len(prefix):]
        if suffix.isdigit():
            indexed.append((int(suffix), candidate))
    return [candidate for _index, candidate in sorted(indexed, reverse=True)]


def _step(kind: str, step_id: str, timestamp: str | None, index: int) -> dict[str, Any]:
    return {"kind": kind, "id": step_id, "ts": timestamp, "index": index}


def skill_steps(session_id: str, directory: str) -> tuple[list[dict[str, Any]], list[str]]:
    """skill_used stage events for one session, plus any unchecked reasons."""
    if not os.path.isdir(directory):
        return [], [f"skill uses unchecked: no hook metrics directory at {directory}"]
    paths = sorted(glob.glob(os.path.join(directory, EVENTS_FILE_PATTERN)))
    if not paths:
        return [], [f"skill uses unchecked: no {EVENTS_FILE_PATTERN} under {directory}"]
    unchecked: list[str] = []
    steps: list[dict[str, Any]] = []
    index = 0
    for path in paths:
        rows, malformed = _read_rows(path)
        if rows is None:
            unchecked.append(f"skill uses unchecked: {path} unreadable")
            continue
        if malformed:
            unchecked.append(f"skill uses unchecked: {malformed} malformed row(s) in {path}")
        for row in rows:
            if str(row.get("session_id") or "") != session_id:
                continue
            if row.get("hook") != SKILL_USAGE_HOOK:
                continue
            if row.get("action") == SKILL_UNCHECKED_ACTION:
                unchecked.append(
                    "skill uses unchecked: skill-usage-log could not read its input "
                    f"({row.get('reason') or 'no reason recorded'})"
                )
                continue
            if row.get("action") != SKILL_USED_ACTION:
                continue
            skill = row.get("skill")
            if not isinstance(skill, str) or not skill:
                unchecked.append("skill uses unchecked: a skill_used row names no skill")
                continue
            steps.append(_step(SKILL_KIND, skill, row.get("ts"), index))
            index += 1
    return steps, unchecked


def hook_steps(session_id: str, directory: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Runner rows for one session whose outcome spoke or blocked."""
    if not os.path.isdir(directory):
        return [], [f"hook firings unchecked: no hook metrics directory at {directory}"]
    runs_path = os.path.join(directory, RUNS_FILE_NAME)
    rotated = _rotated_run_paths(runs_path)
    if not os.path.exists(runs_path) and not rotated:
        return [], [f"hook firings unchecked: no {RUNS_FILE_NAME} under {directory}"]
    unchecked: list[str] = []
    steps: list[dict[str, Any]] = []
    index = 0
    for path in [*rotated, runs_path]:
        rows, malformed = _read_rows(path)
        if rows is None:
            unchecked.append(f"hook firings unchecked: {path} unreadable")
            continue
        if malformed:
            unchecked.append(f"hook firings unchecked: {malformed} malformed row(s) in {path}")
        for row in rows:
            if str(row.get("session_id") or "") != session_id:
                continue
            if row.get("outcome") not in SPEAKING_OUTCOMES:
                continue
            hook = row.get("hook")
            if not isinstance(hook, str) or not hook:
                unchecked.append("hook firings unchecked: a run row names no hook")
                continue
            steps.append(_step(HOOK_KIND, hook, row.get("ts"), index))
            index += 1
    return steps, unchecked


def intervention_steps(path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Human interventions in a Claude transcript, as token_audit classifies them."""
    try:
        rows = token_audit.read_jsonl(path)
    except OSError as exc:
        return [], [f"interventions unchecked: {path} unreadable ({type(exc).__name__}: {exc})"]
    failed_turn_indices = [
        position for position, row in enumerate(rows) if token_audit._is_api_error_line(row)
    ]
    user_messages, review_indices = token_audit._claude_frustration_messages(rows, path)
    extra_kinds = token_audit.claude_restated_after_rejection(rows, user_messages)
    frustration = token_audit.frustration_signals(
        user_messages,
        failed_turn_indices=failed_turn_indices,
        unflagged_indices=review_indices,
        extra_kinds=extra_kinds,
    )
    unchecked: list[str] = []
    if frustration.get("count") is None:
        unchecked.append(f"interventions unchecked: {frustration.get('rationale')}")
    restated_rule = frustration.get("restated_rule") or {}
    if restated_rule.get("status") != "judged":
        unchecked.append(f"interventions partly unchecked: {restated_rule.get('rationale')}")
    steps = [
        _step(INTERVENTION_KIND, "+".join(flagged["kinds"]), flagged.get("ts"), flagged["index"])
        for flagged in frustration.get("flagged") or []
    ]
    return steps, unchecked


def first_user_prompt(path: str, harness: str = "claude") -> str | None:
    """The session's first direct-human message, or None when none can be classified."""
    for utterance in transcript_provenance.direct_human_utterances(path, harness):
        if utterance.text.strip():
            return utterance.text
    return None


def task_type_from_prompt(text: str | None) -> str | None:
    """First matching keyword wins; other when nothing matches; None when undecidable."""
    if not isinstance(text, str) or not text.strip():
        return None
    compact = " ".join(text.split())
    for name, pattern in TASK_TYPE_KEYWORDS:
        if pattern.search(compact):
            return name
    return DEFAULT_TASK_TYPE


def _order_key(step: dict[str, Any]) -> tuple[int, float, int, int]:
    seconds = token_audit._ts_seconds(step.get("ts"))
    return (
        1 if seconds is None else 0,
        0.0 if seconds is None else seconds,
        KIND_TIE_ORDER.get(step["kind"], len(KIND_TIE_ORDER)),
        step["index"],
    )


def order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Steps in time order; undated steps keep their own order at the end."""
    return sorted(steps, key=_order_key)


def step_order(path: str, metrics_dir: str | None = None) -> dict[str, Any]:
    """One session's ordered steps and its keyword-matched task type."""
    harness = cluster_interventions.sniff_kind(path)
    _lineage_id, session_id, _is_subagent = transcript_provenance._path_identity(path)
    if harness != "claude":
        return {
            "path": path,
            "harness": harness,
            "session_id": session_id,
            "task_type": None,
            "first_prompt_excerpt": None,
            "steps": [],
            "step_count": 0,
            "undated_step_count": 0,
            "unchecked": [f"step order unchecked: {harness} transcripts are not read yet"],
        }
    directory = metrics_directory(metrics_dir)
    skills, skill_unchecked = skill_steps(session_id, directory)
    hooks, hook_unchecked = hook_steps(session_id, directory)
    interventions, intervention_unchecked = intervention_steps(path)
    steps = order_steps(skills + hooks + interventions)
    prompt = first_user_prompt(path, harness)
    task_type = task_type_from_prompt(prompt)
    unchecked = skill_unchecked + hook_unchecked + intervention_unchecked
    if task_type is None:
        unchecked.append("task type unchecked: no classifiable first human prompt")
    return {
        "path": path,
        "harness": harness,
        "session_id": session_id,
        "task_type": task_type,
        "first_prompt_excerpt": None if prompt is None else " ".join(prompt.split())[:120],
        "steps": [{"kind": s["kind"], "id": s["id"], "ts": s["ts"]} for s in steps],
        "step_count": len(steps),
        "undated_step_count": sum(1 for s in steps if token_audit._ts_seconds(s["ts"]) is None),
        "unchecked": unchecked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Claude session transcript paths")
    parser.add_argument("--metrics-dir", default=None, help="hook metrics directory")
    parser.add_argument("--out", default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    sessions = [step_order(path, args.metrics_dir) for path in args.paths]
    payload = {
        "sessions": sessions,
        "sessions_read": len(sessions),
        "unchecked_sessions": sum(1 for session in sessions if session["unchecked"]),
    }
    text = json.dumps(payload, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {len(sessions)} session(s) -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
