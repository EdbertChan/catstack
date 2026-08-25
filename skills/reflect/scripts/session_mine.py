#!/usr/bin/env python3
"""Hourly session-mine driver for catstack.

1. Scan local Claude / Cursor / Codex transcripts for repeated interventions.
2. Write ranked clusters to ~/.cache/catstack-session-mine/queue.json.
3. Emit DORA-for-agents metrics into metrics.jsonl (mechanical events file optional).
4. Mark high-confidence clusters as pending headless reflect (never merges).

Opt-in only: install.sh --with-session-mine installs a launchd plist.
Default install does not scan home directories.

Usage:
    session_mine.py run [--hours N] [--state-dir DIR]
    session_mine.py report [--state-dir DIR]
    session_mine.py pending [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import cluster_interventions  # noqa: E402
import dora_ai  # noqa: E402

DEFAULT_STATE_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "catstack-session-mine"
)
# At most one headless pass per cluster hash per this many seconds.
HEADLESS_COOLDOWN_SECONDS = 7 * 24 * 3600
DEFAULT_MIN_SESSIONS = 3
DEFAULT_MIN_UTTERANCES = 5


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
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))),
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
