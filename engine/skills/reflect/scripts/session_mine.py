#!/usr/bin/env python3
"""Session-mine driver for catstack, run as the `session-mine` Invoker worker.

1. Scan local Claude / Cursor / Codex transcripts for repeated interventions.
2. Write ranked clusters to ~/.cache/catstack-session-mine/queue.json.
3. Emit DORA-for-agents metrics into metrics.jsonl (mechanical events file optional).
4. Mark high-confidence clusters as pending headless reflect (never merges).
5. Audit every session modified since the last run, append one row per
   session to audit_trend.tsv, compare with the previous run, and file an
   Invoker task for each session that crosses a filing threshold.

Opt-in only: install.sh --with-session-mine registers the Invoker worker.
Default install does not scan home directories.

Usage:
    session_mine.py run [--hours N] [--state-dir DIR]
    session_mine.py audit [--state-dir DIR] [--first-run-hours N]
    session_mine.py worker [--interval SECONDS] [--once]
    session_mine.py register-worker [--config PATH] [--script PATH]
    session_mine.py distribution [--hours N]
    session_mine.py report [--state-dir DIR]
    session_mine.py pending [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import cluster_interventions  # noqa: E402
import corpus_scan  # noqa: E402
import dora_ai  # noqa: E402
import token_audit  # noqa: E402
import transcript_provenance  # noqa: E402

DEFAULT_STATE_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "catstack-session-mine"
)
# At most one headless pass per cluster hash per this many seconds.
HEADLESS_COOLDOWN_SECONDS = 7 * 24 * 3600
DEFAULT_MIN_SESSIONS = 3
DEFAULT_MIN_UTTERANCES = 5

WORKER_KIND = "session-mine"
DEFAULT_INVOKER_CONFIG = os.path.join(os.path.expanduser("~"), ".invoker", "config.json")
DEFAULT_WORKER_INTERVAL_SECONDS = 3600
AUDIT_FIRST_RUN_HOURS = 24.0
AUDIT_MAX_FILE_BYTES = corpus_scan.DEFAULT_MAX_FILE_BYTES
AUDIT_HARNESS_ROOTS = (
    ("claude", (".claude", "projects"), "*.jsonl", ""),
    ("codex", (".codex", "sessions"), "rollout-*.jsonl", ""),
    ("cursor", (".cursor", "projects"), "*.jsonl", "/agent-transcripts/"),
)

INTERVENTION_FILING_VALUE = "yes"
INTERVENTION_MEASURED_DISTRIBUTION = {"sessions": 1180, "yes": 20, "no": 843, "unchecked": 317}
NARROWED_FILING_THRESHOLD = 0
NARROWED_MEASURED_DISTRIBUTION = {"sessions": 1180, "0": 160, "1": 1, "2": 2, "3+": 0, "unchecked": 1017}
OVER_THRESHOLD_SESSIONS_PER_DAY_MEASURED = {"active_days": 12, "median": 1, "max": 6}
MAX_FILINGS_PER_SESSION = 1
MAX_FILINGS_PER_WINDOW = OVER_THRESHOLD_SESSIONS_PER_DAY_MEASURED["max"]
FILING_WINDOW_SECONDS = 24 * 3600
MAX_TURN_PAIRS = 10
EXCERPT_CHARS = 300

UNCHECKED = "unchecked"
TREND_FILE = "audit_trend.tsv"
RUNS_FILE = "audit_runs.jsonl"
AUDIT_STATE_FILE = "audit_state.json"
AUDIT_LOCK_FILE = "audit.lock"
TREND_COLUMNS = (
    "date",
    "harness",
    "session_id",
    "intervention_must_automate",
    "intervention_count",
    "narrowed",
    "undetermined",
    "tokens",
)
FILED_TASK_INSTRUCTION = (
    "Run reflect on this session as a headless pass: follow the headless reflect "
    "contract in engine/skills/reflect/references/session-mine.md, treat the turn "
    "pairs above as the evidence, and land the strongest structural fix as a pull "
    "request. Never merge. If the transcript shows no fixable cause, say so and "
    "stop without a change."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_state_dir(state_dir: str) -> None:
    os.makedirs(state_dir, exist_ok=True)


def load_json(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str, payload: Any) -> None:
    ensure_state_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def discover_intervention_paths(hours: float) -> list[str]:
    import corpus_scan  # noqa: WPS433

    pattern = (
        r"make (a |the )?pr|open (a |the )?pr|commit and push|"
        r"/reflect|eli ?5|automate me|try again|just do it"
    )
    return [path for _kind, path, _host in corpus_scan.discover_local(pattern, hours)]


def open_pr_hashes_for_cluster(cluster_hash: str) -> list[str]:
    """Best-effort: list open PR titles/urls mentioning the cluster hash. Fail-open."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--search",
                f"[auto] {cluster_hash}",
                "--json",
                "number,url,title",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [str(r.get("url") or r.get("number")) for r in rows if cluster_hash in (r.get("title") or "")]


def run_mine(
    *,
    hours: float,
    state_dir: str,
    min_sessions: int,
    min_utterances: int,
    events_path: str | None,
) -> dict[str, Any]:
    ensure_state_dir(state_dir)
    paths = discover_intervention_paths(hours)
    utterances: list[dict[str, Any]] = []
    for path in paths:
        utterances.extend(cluster_interventions.extract_user_utterances(path))
    clusters = cluster_interventions.cluster_utterances(
        utterances,
        min_sessions=min_sessions,
        min_utterances=min_utterances,
    )

    cooldown = load_json(os.path.join(state_dir, "headless_cooldown.json"), {})
    now = time.time()
    pending: list[dict[str, Any]] = []
    for cluster in clusters:
        if not cluster.get("high_confidence"):
            continue
        if not cluster.get("circumstance_complete"):
            cluster = dict(cluster)
            cluster["blocked_reason"] = "circumstance_incomplete"
            pending.append(cluster)
            continue
        ch = cluster["hash"]
        last = float(cooldown.get(ch) or 0)
        if now - last < HEADLESS_COOLDOWN_SECONDS:
            cluster = dict(cluster)
            cluster["blocked_reason"] = "cooldown"
            pending.append(cluster)
            continue
        existing = open_pr_hashes_for_cluster(ch)
        if existing:
            cluster = dict(cluster)
            cluster["blocked_reason"] = "open_pr"
            cluster["open_prs"] = existing
            pending.append(cluster)
            continue
        cluster = dict(cluster)
        cluster["ready_for_headless"] = True
        pending.append(cluster)

    queue = {
        "updated_at": _now_iso(),
        "hours": hours,
        "paths_scanned": len(paths),
        "clusters": clusters,
        "pending_headless": [c for c in pending if c.get("ready_for_headless")],
        "blocked": [c for c in pending if not c.get("ready_for_headless")],
    }
    write_json(os.path.join(state_dir, "queue.json"), queue)

    metrics_path = os.path.join(state_dir, "metrics.jsonl")
    if events_path and os.path.isfile(events_path):
        with open(events_path, encoding="utf-8") as handle:
            events = json.load(handle)
        if isinstance(events, list):
            summary = dora_ai.summarize(events, window_days=max(hours / 24.0, 1.0))
            dora_ai.append_metrics(metrics_path, summary)
            write_json(os.path.join(state_dir, "metrics_latest.json"), summary)

    return queue


def print_report(state_dir: str) -> None:
    latest = load_json(os.path.join(state_dir, "metrics_latest.json"), None)
    if latest:
        print(dora_ai.format_report(latest))
    else:
        print("no metrics_latest.json yet — pass --events on run, or wait for data")
    queue = load_json(os.path.join(state_dir, "queue.json"), {})
    pending = queue.get("pending_headless") or []
    print(f"\npending headless clusters: {len(pending)}")
    for c in pending[:10]:
        print(
            f"  - {c.get('cluster_key')} hash={c.get('hash')} "
            f"sessions={c.get('session_count')} utterances={c.get('utterance_count')}"
        )


def mark_headless_dispatched(state_dir: str, cluster_hash: str) -> None:
    path = os.path.join(state_dir, "headless_cooldown.json")
    cooldown = load_json(path, {})
    cooldown[cluster_hash] = time.time()
    write_json(path, cooldown)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_audit_sessions(since: float, home: str | None = None) -> list[tuple[str, str]]:
    base = home or os.path.expanduser("~")
    found: list[tuple[str, str, float]] = []
    for harness, parts, pattern, required in AUDIT_HARNESS_ROOTS:
        root = os.path.join(base, *parts)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if not fnmatch.fnmatch(name, pattern):
                    continue
                path = os.path.join(dirpath, name)
                normalized = path.replace("\\", "/")
                if "/subagents/" in normalized or (required and required not in normalized):
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except OSError as exc:
                    print(f"session-mine: skip {path}: {exc!r}", file=sys.stderr)
                    continue
                if mtime <= since:
                    continue
                if harness == "claude" and corpus_scan.is_sidechain_transcript(path):
                    continue
                found.append((harness, path, mtime))
    found.sort(key=lambda item: item[2])
    return [(harness, path) for harness, path, _mtime in found]


def _session_id(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"] for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def _assistant_text(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    if row.get("type") == "assistant":
        content = message.get("content")
    elif row.get("type") == "response_item" and payload.get("role") == "assistant":
        content = payload.get("content")
    elif row.get("role") == "assistant":
        content = message.get("content")
    else:
        return ""
    return _block_text(content).strip()


def _excerpt(text: str) -> str:
    return " ".join((text or "").split())[:EXCERPT_CHARS]


def _previous_assistant_text(rows: list[Any], index: int) -> str:
    for i in range(min(index, len(rows)) - 1, -1, -1):
        text = _assistant_text(rows[i])
        if text:
            return text
    return ""


def offending_turn_pairs(harness: str, path: str, frustration: dict, conformance: dict | None) -> list[dict]:
    rows = token_audit.read_jsonl(path)
    human = {
        u.index: u.text
        for u in transcript_provenance.direct_human_utterances(
            path, harness, include_queue_operations=harness == "claude",
        )
    }
    intervention_kinds = set(token_audit.INTERVENTION_KINDS) | {"verbatim-repeat"}
    pairs: list[dict] = []
    for flagged in frustration.get("flagged") or []:
        kinds = sorted(set(flagged.get("kinds") or []) & intervention_kinds)
        if not kinds:
            continue
        index = flagged["index"]
        pairs.append({
            "kind": "intervention:" + "+".join(kinds),
            "line": index,
            "agent": _excerpt(_previous_assistant_text(rows, index)),
            "user": _excerpt(human.get(index) or flagged.get("excerpt") or ""),
        })
    for directive in (conformance or {}).get("directives") or []:
        if directive.get("outcome") != "narrowed":
            continue
        evidence = directive.get("evidence") or []
        pairs.append({
            "kind": "narrowed",
            "line": directive["index"],
            "user": _excerpt(human.get(directive["index"]) or directive.get("excerpt") or ""),
            "agent": _excerpt("; ".join(
                f"line {ev['index']} {ev['tool']}: {ev['predicate']}" for ev in evidence[:3]
            )),
        })
    return pairs


def audit_session(harness: str, path: str, max_file_bytes: int | None = AUDIT_MAX_FILE_BYTES) -> dict:
    record: dict[str, Any] = {
        "harness": harness,
        "session_id": _session_id(path),
        "path": path,
        "intervention_must_automate": UNCHECKED,
        "intervention_count": UNCHECKED,
        "narrowed": UNCHECKED,
        "undetermined": UNCHECKED,
        "tokens": UNCHECKED,
        "reasons": [],
        "pairs": [],
    }
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        record["reasons"].append(f"unreadable: {exc!r}")
        return record
    if max_file_bytes is not None and size > max_file_bytes:
        record["reasons"].append(f"{size} bytes is above the {max_file_bytes}-byte audit cap")
        return record
    audit = {
        "claude": token_audit.audit_claude,
        "codex": token_audit.audit_codex,
        "cursor": token_audit.audit_cursor,
    }[harness]
    with contextlib.redirect_stdout(io.StringIO()):
        result = audit(path)
    frustration = result.get("frustration") or {}
    yes, count, rationale = token_audit.intervention_must_automate(frustration)
    if yes is None:
        record["reasons"].append(f"intervention: {rationale}")
    else:
        record["intervention_must_automate"] = "yes" if yes else "no"
        record["intervention_count"] = count
    conformance = result.get("conformance")
    if conformance is None:
        record["reasons"].append(f"conformance: not measured for {harness} transcripts")
    elif conformance.get("scoped") is None:
        record["reasons"].append(f"conformance: {conformance.get('rationale')}")
    else:
        record["narrowed"] = conformance["narrowed"]
        record["undetermined"] = conformance["undetermined"]
    tokens = result.get("combined_total", result.get("total"))
    if isinstance(tokens, int):
        record["tokens"] = tokens
    else:
        record["reasons"].append(f"tokens: {harness} transcripts carry no usage fields")
    if crosses_threshold(record):
        record["pairs"] = offending_turn_pairs(harness, path, frustration, conformance)
    return record


def crosses_threshold(record: dict) -> bool:
    narrowed = record.get("narrowed")
    return (
        record.get("intervention_must_automate") == INTERVENTION_FILING_VALUE
        or (isinstance(narrowed, int) and narrowed > NARROWED_FILING_THRESHOLD)
    )


def _count(value: Any) -> int:
    return value if isinstance(value, int) else 0


def session_key(record: dict) -> str:
    return f"{record['harness']}:{record['session_id']}"


def append_trend_rows(state_dir: str, date: str, records: list[dict]) -> str:
    path = os.path.join(state_dir, TREND_FILE)
    new_file = not os.path.isfile(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8") as handle:
        if new_file:
            handle.write("\t".join(TREND_COLUMNS) + "\n")
        for record in records:
            values = {**record, "date": date}
            handle.write("\t".join(str(values[column]) for column in TREND_COLUMNS) + "\n")
    return path


def _last_run(state_dir: str) -> dict | None:
    path = os.path.join(state_dir, RUNS_FILE)
    if not os.path.isfile(path):
        return None
    last = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"session-mine: unreadable line in {path}: {exc}", file=sys.stderr)
    return last


def summarize_run(date: str, records: list[dict], previous_counts: dict) -> dict:
    checked = [r for r in records if r["intervention_must_automate"] != UNCHECKED]
    rising = []
    for record in records:
        before = previous_counts.get(session_key(record))
        if not before:
            continue
        deltas = {
            field: _count(record[field]) - _count(before.get(field))
            for field in ("intervention_count", "narrowed")
        }
        if any(delta > 0 for delta in deltas.values()):
            rising.append({"session": session_key(record), **deltas})
    return {
        "date": date,
        "sessions": len(records),
        "unchecked": len(records) - len(checked),
        "intervention_yes": sum(1 for r in records if r["intervention_must_automate"] == "yes"),
        "intervention_total": sum(_count(r["intervention_count"]) for r in records),
        "narrowed_sessions": sum(1 for r in records if _count(r["narrowed"]) > 0),
        "narrowed_total": sum(_count(r["narrowed"]) for r in records),
        "tokens_total": sum(_count(r["tokens"]) for r in records),
        "over_threshold": sum(1 for r in records if crosses_threshold(r)),
        "rising": rising,
    }


def compare_runs(current: dict, previous: dict | None) -> dict:
    if not previous:
        return {}
    fields = ("sessions", "intervention_yes", "narrowed_total", "tokens_total", "over_threshold")
    return {field: current[field] - _count(previous.get(field)) for field in fields}


def select_turn_pairs(pairs: list[dict]) -> list[dict]:
    narrowed = [p for p in pairs if p["kind"] == "narrowed"]
    interventions = [p for p in pairs if p["kind"] != "narrowed"]
    half = MAX_TURN_PAIRS // 2
    chosen = narrowed[:half] + interventions[:half]
    rest = narrowed[half:] + interventions[half:]
    chosen += rest[:MAX_TURN_PAIRS - len(chosen)]
    return sorted(chosen, key=lambda p: p["line"])


def build_filing_plan(record: dict, repo_url: str) -> dict:
    lines = [
        "The session-mine worker flagged a session that crossed a filing threshold.",
        "",
        f"session: {record['harness']} {record['session_id']}",
        f"transcript: {record['path']}",
        f"intervention-must-automate: {record['intervention_must_automate']} "
        f"(count={record['intervention_count']})",
        f"instruction-conformance: narrowed={record['narrowed']} undetermined={record['undetermined']}",
        f"tokens: {record['tokens']}",
        "",
        "Offending turn pairs:",
    ]
    for n, pair in enumerate(select_turn_pairs(record["pairs"]), 1):
        lines.append(f"{n}. [{pair['kind']}] line {pair['line']}")
        lines.append(f"   agent: {pair['agent']!r}")
        lines.append(f"   user: {pair['user']!r}")
    if len(record["pairs"]) > MAX_TURN_PAIRS:
        lines.append(f"... {len(record['pairs']) - MAX_TURN_PAIRS} more in the transcript")
    lines += ["", FILED_TASK_INSTRUCTION]
    short = record["session_id"][:12]
    name = (
        f"[auto] session-mine {record['harness']} {short} "
        f"i{_count(record['intervention_count'])} n{_count(record['narrowed'])}"
    )
    return {
        "name": name,
        "repoUrl": repo_url,
        "onFinish": "pull_request",
        "mergeMode": "external_review",
        "reviewProvider": "github",
        "tasks": [{
            "id": "reflect-session",
            "description": f"Reflect on flagged {record['harness']} session {short}",
            "prompt": "\n".join(lines) + "\n",
        }],
    }


def filing_decisions(
    records: list[dict], state: dict, now: float, max_filings: int = MAX_FILINGS_PER_WINDOW,
) -> list[tuple[dict, str]]:
    filed = state.get("filed") or {}
    history = [f for f in state.get("filings") or [] if now - float(f.get("at") or 0) < FILING_WINDOW_SECONDS]
    budget = max_filings - len(history)
    per_session = Counter(f.get("key") for f in history)
    candidates = sorted(
        (r for r in records if crosses_threshold(r)),
        key=lambda r: (_count(r["intervention_count"]) + _count(r["narrowed"])),
        reverse=True,
    )
    decisions = []
    for record in candidates:
        key = session_key(record)
        before = filed.get(key)
        if before and not any(
            _count(record[field]) > _count(before.get(field))
            for field in ("intervention_count", "narrowed")
        ):
            decisions.append((record, "already-filed"))
        elif per_session[key] >= MAX_FILINGS_PER_SESSION:
            decisions.append((record, "session-rate-cap"))
        elif budget <= 0:
            decisions.append((record, "window-rate-cap"))
        else:
            budget -= 1
            per_session[key] += 1
            decisions.append((record, "file"))
    return decisions


def resolve_repo_url(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "-C", SCRIPTS_DIR, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"session-mine: cannot read git origin from {SCRIPTS_DIR}: {exc!r}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"session-mine: git origin lookup failed in {SCRIPTS_DIR}: {result.stderr.strip()}", file=sys.stderr)
        return None
    return result.stdout.strip() or None


def invoker_filer(invoker_cli: str | None, state_dir: str) -> Callable[[dict], str]:
    def file_plan(plan: dict) -> str:
        cli = invoker_cli or shutil.which("invoker-cli")
        if not cli:
            raise RuntimeError("invoker-cli is not on this process's PATH; pass --invoker-cli")
        filings_dir = os.path.join(state_dir, "filings")
        ensure_state_dir(filings_dir)
        digest = hashlib.sha1(plan["name"].encode()).hexdigest()[:12]
        plan_path = os.path.join(filings_dir, f"{digest}.yaml")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=2)
            handle.write("\n")
        result = subprocess.run(
            [cli, "run", plan_path, "--live", "--json"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{cli} run {plan_path} exited {result.returncode}: "
                f"{(result.stderr or result.stdout).strip()[-500:]}"
            )
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            workflow_id = ((payload or {}).get("workflow") or {}).get("id")
            if workflow_id:
                return str(workflow_id)
        raise RuntimeError(f"{cli} run {plan_path} printed no workflow id: {result.stdout.strip()[-500:]}")
    return file_plan


@contextlib.contextmanager
def _audit_lock(state_dir: str):
    path = os.path.join(state_dir, AUDIT_LOCK_FILE)
    with open(path, "a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_audit(
    *,
    state_dir: str,
    filer: Callable[[dict], str] | None,
    repo_url: str | None,
    first_run_hours: float = AUDIT_FIRST_RUN_HOURS,
    max_file_bytes: int | None = AUDIT_MAX_FILE_BYTES,
    max_filings: int = MAX_FILINGS_PER_WINDOW,
    home: str | None = None,
    now: float | None = None,
) -> dict | None:
    ensure_state_dir(state_dir)
    with _audit_lock(state_dir) as held:
        if not held:
            print(f"session-mine: another audit holds {os.path.join(state_dir, AUDIT_LOCK_FILE)}; skipping", file=sys.stderr)
            return None
        return _run_audit_locked(
            state_dir=state_dir, filer=filer, repo_url=repo_url, first_run_hours=first_run_hours,
            max_file_bytes=max_file_bytes, max_filings=max_filings, home=home, now=now,
        )


def _run_audit_locked(*, state_dir, filer, repo_url, first_run_hours, max_file_bytes, max_filings, home, now) -> dict:
    state_path = os.path.join(state_dir, AUDIT_STATE_FILE)
    state = load_json(state_path, {})
    started = time.time() if now is None else now
    since = float(state.get("last_run_started_at") or started - first_run_hours * 3600)
    date = _iso(started)
    records = []
    for harness, path in discover_audit_sessions(since, home=home):
        try:
            records.append(audit_session(harness, path, max_file_bytes))
        except Exception as exc:
            print(f"session-mine: audit failed for {harness} {path}:\n{traceback.format_exc()}", file=sys.stderr)
            records.append({
                "harness": harness, "session_id": _session_id(path), "path": path,
                "intervention_must_automate": UNCHECKED, "intervention_count": UNCHECKED,
                "narrowed": UNCHECKED, "undetermined": UNCHECKED, "tokens": UNCHECKED,
                "reasons": [f"audit error: {exc!r}"], "pairs": [],
            })
    append_trend_rows(state_dir, date, records)
    previous_counts = state.get("sessions") or {}
    summary = summarize_run(date, records, previous_counts)
    summary["since"] = _iso(since)
    summary["vs_previous_run"] = compare_runs(summary, _last_run(state_dir))

    filed = dict(state.get("filed") or {})
    filings = [f for f in state.get("filings") or [] if started - float(f.get("at") or 0) < FILING_WINDOW_SECONDS]
    outcomes: Counter = Counter()
    for record, decision in filing_decisions(records, state, started, max_filings):
        key = session_key(record)
        if decision != "file":
            outcomes[decision] += 1
            continue
        if filer is None or not repo_url:
            outcomes["filing-unavailable"] += 1
            print(f"session-mine: cannot file {key}: filer={'set' if filer else 'none'} repo_url={repo_url!r}", file=sys.stderr)
            continue
        try:
            workflow_id = filer(build_filing_plan(record, repo_url))
        except Exception as exc:
            outcomes["filing-failed"] += 1
            print(f"session-mine: filing failed for {key}: {exc}", file=sys.stderr)
            continue
        outcomes["filed"] += 1
        filed[key] = {
            "intervention_count": _count(record["intervention_count"]),
            "narrowed": _count(record["narrowed"]),
            "workflow_id": workflow_id,
            "filed_at": _iso(started),
        }
        filings.append({"key": key, "at": started, "workflow_id": workflow_id})
        print(f"session-mine: filed {key} -> workflow {workflow_id}", file=sys.stderr)
    summary["filing"] = dict(outcomes)

    sessions = dict(previous_counts)
    for record in records:
        sessions[session_key(record)] = {
            "intervention_count": record["intervention_count"],
            "narrowed": record["narrowed"],
            "tokens": record["tokens"],
            "date": date,
        }
    state.update(last_run_started_at=started, sessions=sessions, filed=filed, filings=filings)
    write_json(state_path, state)
    with open(os.path.join(state_dir, RUNS_FILE), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary) + "\n")
    return summary


def format_audit_summary(summary: dict) -> str:
    delta = summary.get("vs_previous_run") or {}

    def field(name: str) -> str:
        return f"{name}={summary[name]}" + (f" ({delta[name]:+d})" if name in delta else "")

    parts = [
        f"session-mine audit {summary['date']} since {summary['since']}:",
        field("sessions"),
        f"unchecked={summary['unchecked']}",
        field("intervention_yes"),
        field("narrowed_total"),
        field("tokens_total"),
        field("over_threshold"),
        f"rising={len(summary['rising'])}",
        "filing=" + (json.dumps(summary["filing"], sort_keys=True) if summary["filing"] else "{}"),
    ]
    if not delta:
        parts.append("(first run: no previous run to compare)")
    return " ".join(parts)


def measure_distribution(hours: float | None, max_file_bytes: int | None, home: str | None = None) -> dict:
    since = 0.0 if hours is None else time.time() - hours * 3600
    intervention: Counter = Counter()
    narrowed: Counter = Counter()
    harnesses: Counter = Counter()
    for harness, path in discover_audit_sessions(since, home=home):
        harnesses[harness] += 1
        try:
            record = audit_session(harness, path, max_file_bytes)
        except Exception:
            print(f"session-mine: audit failed for {harness} {path}:\n{traceback.format_exc()}", file=sys.stderr)
            intervention[UNCHECKED] += 1
            narrowed[UNCHECKED] += 1
            continue
        intervention[str(record["intervention_must_automate"])] += 1
        value = record["narrowed"]
        narrowed[UNCHECKED if value == UNCHECKED else str(value) if value < 3 else "3+"] += 1
    return {
        "sessions": sum(harnesses.values()),
        "harnesses": dict(harnesses),
        "intervention_must_automate": dict(intervention),
        "narrowed": dict(narrowed),
    }


def run_worker(args: argparse.Namespace) -> int:
    while True:
        try:
            run_mine(
                hours=args.hours,
                state_dir=args.state_dir,
                min_sessions=DEFAULT_MIN_SESSIONS,
                min_utterances=DEFAULT_MIN_UTTERANCES,
                events_path=None,
            )
        except Exception:
            print(f"session-mine: cluster mining failed:\n{traceback.format_exc()}", file=sys.stderr)
        try:
            summary = run_audit(
                state_dir=args.state_dir,
                filer=invoker_filer(args.invoker_cli, args.state_dir),
                repo_url=resolve_repo_url(args.repo_url),
                first_run_hours=args.first_run_hours,
                max_filings=args.max_filings_per_window,
            )
            if summary:
                print(format_audit_summary(summary), file=sys.stderr, flush=True)
        except Exception:
            print(f"session-mine: audit run failed:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


def register_worker(
    config_path: str, *, python: str, script: str, interval: int, extra_args: list[str] | None = None,
) -> str:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"no Invoker config at {config_path}; install Invoker first")
    with open(config_path, encoding="utf-8") as handle:
        raw = handle.read()
    config = json.loads(raw)
    entry = {
        "kind": WORKER_KIND,
        "launch": {
            "executable": python,
            "args": [script, "worker", "--interval", str(interval), *(extra_args or [])],
            "cwd": os.path.dirname(script),
        },
    }
    workers = [w for w in config.get("externalWorkers") or [] if not (isinstance(w, dict) and w.get("kind") == WORKER_KIND)]
    current = next((w for w in config.get("externalWorkers") or [] if isinstance(w, dict) and w.get("kind") == WORKER_KIND), None)
    if current == entry:
        return "unchanged"
    config["externalWorkers"] = workers + [entry]
    backup = f"{config_path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(config_path, backup)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(config, indent=2) + "\n")
    shutil.copymode(config_path, tmp)
    os.replace(tmp, config_path)
    return f"registered (backup {backup})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="scan + write queue (+ optional metrics)")
    run_p.add_argument("--hours", type=float, default=168.0)
    run_p.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    run_p.add_argument("--min-sessions", type=int, default=DEFAULT_MIN_SESSIONS)
    run_p.add_argument("--min-utterances", type=int, default=DEFAULT_MIN_UTTERANCES)
    run_p.add_argument("--events", default=None, help="optional DORA events JSON list")

    report_p = sub.add_parser("report", help="print DORA rollup + pending clusters")
    report_p.add_argument("--state-dir", default=DEFAULT_STATE_DIR)

    pending_p = sub.add_parser("pending", help="print ready-for-headless clusters as JSON")
    pending_p.add_argument("--state-dir", default=DEFAULT_STATE_DIR)

    mark_p = sub.add_parser("mark-dispatched", help="record headless cooldown for a hash")
    mark_p.add_argument("hash")
    mark_p.add_argument("--state-dir", default=DEFAULT_STATE_DIR)

    def add_audit_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
        parser.add_argument("--first-run-hours", type=float, default=AUDIT_FIRST_RUN_HOURS)
        parser.add_argument("--invoker-cli", default=None)
        parser.add_argument("--repo-url", default=None)
        parser.add_argument("--max-filings-per-window", type=int, default=MAX_FILINGS_PER_WINDOW)

    audit_p = sub.add_parser("audit", help="one audit pass: trend rows, run comparison, filings")
    add_audit_args(audit_p)

    worker_p = sub.add_parser("worker", help=f"the {WORKER_KIND} Invoker worker loop")
    add_audit_args(worker_p)
    worker_p.add_argument("--hours", type=float, default=168.0)
    worker_p.add_argument("--interval", type=int, default=DEFAULT_WORKER_INTERVAL_SECONDS)
    worker_p.add_argument("--once", action="store_true")

    register_p = sub.add_parser("register-worker", help=f"register the {WORKER_KIND} Invoker worker kind")
    register_p.add_argument("--config", default=DEFAULT_INVOKER_CONFIG)
    register_p.add_argument("--script", default=os.path.abspath(__file__))
    register_p.add_argument("--python", default=sys.executable)
    register_p.add_argument("--interval", type=int, default=DEFAULT_WORKER_INTERVAL_SECONDS)
    register_p.add_argument("worker_args", nargs="*")

    dist_p = sub.add_parser("distribution", help="measure the filing-threshold distribution over the corpus")
    dist_p.add_argument("--hours", type=float, default=None)
    dist_p.add_argument("--max-file-bytes", type=int, default=AUDIT_MAX_FILE_BYTES)

    args = ap.parse_args(argv)
    if args.cmd == "run":
        queue = run_mine(
            hours=args.hours,
            state_dir=args.state_dir,
            min_sessions=args.min_sessions,
            min_utterances=args.min_utterances,
            events_path=args.events,
        )
        ready = len(queue.get("pending_headless") or [])
        print(
            f"session_mine: scanned={queue.get('paths_scanned')} "
            f"clusters={len(queue.get('clusters') or [])} "
            f"ready_headless={ready} -> {args.state_dir}/queue.json",
            file=sys.stderr,
        )
        return 0
    if args.cmd == "report":
        print_report(args.state_dir)
        return 0
    if args.cmd == "pending":
        queue = load_json(os.path.join(args.state_dir, "queue.json"), {})
        print(json.dumps(queue.get("pending_headless") or [], indent=2))
        return 0
    if args.cmd == "mark-dispatched":
        mark_headless_dispatched(args.state_dir, args.hash)
        print(f"marked {args.hash}", file=sys.stderr)
        return 0
    if args.cmd == "audit":
        summary = run_audit(
            state_dir=args.state_dir,
            filer=invoker_filer(args.invoker_cli, args.state_dir),
            repo_url=resolve_repo_url(args.repo_url),
            first_run_hours=args.first_run_hours,
            max_filings=args.max_filings_per_window,
        )
        if summary is None:
            return 1
        print(format_audit_summary(summary))
        return 0
    if args.cmd == "worker":
        return run_worker(args)
    if args.cmd == "register-worker":
        result = register_worker(
            args.config, python=args.python, script=os.path.abspath(args.script), interval=args.interval,
            extra_args=args.worker_args,
        )
        print(f"{WORKER_KIND}: {result} in {args.config}")
        return 0
    if args.cmd == "distribution":
        print(json.dumps(measure_distribution(args.hours, args.max_file_bytes), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
