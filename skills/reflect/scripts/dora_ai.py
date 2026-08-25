#!/usr/bin/env python3
"""DORA-for-agents metrics from mechanical event streams.

Clocks (locked in session-mine plan):
  lead_pickup_seconds   — plan approved → first mutating work
  deploy_frequency      — merged PRs / day
  mttr_seconds          — thrash signal → fix + verify
  rework_rate           — failed executions / started executions
  post_merge_fail_rate  — failed merges / merged PRs

Elite thresholds:
  lead < 15 min, deploys >= 1/day (elite: multiple), MTTR < 1h,
  rework_rate < 0.15, post_merge_fail_rate < 0.15

Never reads real transcripts by default — callers pass structured events.
Output rows are for ~/.cache only, never git.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

ELITE = {
    "lead_pickup_seconds": 15 * 60,
    "deploy_frequency_per_day": 1.0,  # elite floor; "multiple" = >= 2
    "mttr_seconds": 60 * 60,
    "rework_rate": 0.15,
    "post_merge_fail_rate": 0.15,
}


def _parse_ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None
    return None


def lead_pickup_seconds(events: list[dict[str, Any]]) -> list[float]:
    """Pairs of plan_approved → first_mutating_work within the same execution_id."""
    approved: dict[str, float] = {}
    results: list[float] = []
    for ev in sorted(events, key=lambda e: _parse_ts(e.get("ts")) or 0):
        ts = _parse_ts(ev.get("ts"))
        if ts is None:
            continue
        eid = ev.get("execution_id") or "default"
        kind = ev.get("kind")
        if kind == "plan_approved":
            approved[eid] = ts
        elif kind == "first_mutating_work" and eid in approved:
            delta = max(0.0, ts - approved.pop(eid))
            # Zero means missing clocks (same stamp) — not a real pickup sample.
            if delta > 0:
                results.append(delta)
    return results


def deploy_frequency_per_day(events: list[dict[str, Any]], *, window_days: float = 7.0) -> dict[str, Any]:
    merges = [e for e in events if e.get("kind") == "pr_merged"]
    auto = sum(1 for e in merges if e.get("auto"))
    human_asked = sum(1 for e in merges if e.get("human_asked") and not e.get("auto"))
    human_only = len(merges) - auto - human_asked
    per_day = len(merges) / window_days if window_days > 0 else 0.0
    return {
        "merged": len(merges),
        "per_day": per_day,
        "auto": auto,
        "human_asked": human_asked,
        "human_only": human_only,
        "window_days": window_days,
    }


def mttr_seconds(events: list[dict[str, Any]]) -> list[float]:
    """thrash_signal → recovered_verified, same incident_id. Skill PRs do not end MTTR."""
    open_incidents: dict[str, float] = {}
    results: list[float] = []
    for ev in sorted(events, key=lambda e: _parse_ts(e.get("ts")) or 0):
        ts = _parse_ts(ev.get("ts"))
        if ts is None:
            continue
        iid = ev.get("incident_id") or "default"
        kind = ev.get("kind")
        if kind == "thrash_signal" and iid not in open_incidents:
            open_incidents[iid] = ts
        elif kind == "recovered_verified" and iid in open_incidents:
            delta = max(0.0, ts - open_incidents.pop(iid))
            if delta > 0:
                results.append(delta)
        elif kind == "skill_pr_opened":
            # Explicitly ignored for MTTR end.
            continue
    return results


def rework_rate(events: list[dict[str, Any]]) -> dict[str, Any]:
    """failed / started executions. One fail per execution_id (no double count)."""
    started = {e.get("execution_id") for e in events if e.get("kind") == "execution_started"}
    started.discard(None)
    failed_ids: set[Any] = set()
    for e in events:
        if e.get("kind") in ("execution_thrashed", "execution_discarded", "execution_rewritten"):
            eid = e.get("execution_id")
            if eid is not None:
                failed_ids.add(eid)
    # Only count fails that were started
    failed = failed_ids & started if started else failed_ids
    n_started = len(started) if started else len(failed_ids | started)
    # If no explicit starts, treat unique fail ids + successful finishes as denom? Prefer starts.
    if not started:
        n_started = len(failed_ids)  # avoid div0 noise when empty
    rate = (len(failed) / n_started) if n_started else 0.0
    return {"started": n_started, "failed": len(failed), "rate": rate}


def post_merge_fail_rate(events: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {e.get("pr_id") for e in events if e.get("kind") == "pr_merged"}
    merged.discard(None)
    failed = {
        e.get("pr_id")
        for e in events
        if e.get("kind") in ("pr_reverted", "pr_hotfix", "pr_thrashed_after_merge")
    }
    failed.discard(None)
    failed &= merged if merged else failed
    n = len(merged)
    rate = (len(failed) / n) if n else 0.0
    return {"merged": n, "failed": len(failed), "rate": rate}


def summarize(events: list[dict[str, Any]], *, window_days: float = 7.0) -> dict[str, Any]:
    leads = lead_pickup_seconds(events)
    mttrs = mttr_seconds(events)
    deploys = deploy_frequency_per_day(events, window_days=window_days)
    rework = rework_rate(events)
    post = post_merge_fail_rate(events)

    def median(xs: list[float]) -> float | None:
        if not xs:
            return None
        xs = sorted(xs)
        mid = len(xs) // 2
        if len(xs) % 2:
            return xs[mid]
        return (xs[mid - 1] + xs[mid]) / 2

    lead_med = median(leads)
    mttr_med = median(mttrs)
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lead_pickup": {
            "samples": leads,
            "median_seconds": lead_med,
            "elite": lead_med is not None and lead_med < ELITE["lead_pickup_seconds"],
            "threshold_seconds": ELITE["lead_pickup_seconds"],
        },
        "deploy_frequency": {
            **deploys,
            "elite": deploys["per_day"] >= 2.0,
            "threshold_per_day": 2.0,
        },
        "mttr": {
            "samples": mttrs,
            "median_seconds": mttr_med,
            "elite": mttr_med is not None and mttr_med < ELITE["mttr_seconds"],
            "threshold_seconds": ELITE["mttr_seconds"],
        },
        "rework_rate": {
            **rework,
            "elite": rework["rate"] < ELITE["rework_rate"],
            "threshold": ELITE["rework_rate"],
        },
        "post_merge_fail_rate": {
            **post,
            "elite": post["rate"] < ELITE["post_merge_fail_rate"],
            "threshold": ELITE["post_merge_fail_rate"],
        },
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = ["=== DORA-for-agents (weekly rollup) ==="]
    lead = summary["lead_pickup"]
    lines.append(
        f"Lead (pickup): median={lead['median_seconds']}s "
        f"elite={'yes' if lead['elite'] else 'no'} (threshold {lead['threshold_seconds']}s)"
    )
    dep = summary["deploy_frequency"]
    lines.append(
        f"Deploy frequency: {dep['per_day']:.2f}/day "
        f"(merged={dep['merged']}, auto={dep['auto']}) "
        f"elite={'yes' if dep['elite'] else 'no'}"
    )
    mttr = summary["mttr"]
    lines.append(
        f"MTTR: median={mttr['median_seconds']}s "
        f"elite={'yes' if mttr['elite'] else 'no'} (threshold {mttr['threshold_seconds']}s)"
    )
    rw = summary["rework_rate"]
    lines.append(
        f"Rework rate: {rw['rate']:.1%} ({rw['failed']}/{rw['started']}) "
        f"elite={'yes' if rw['elite'] else 'no'}"
    )
    pm = summary["post_merge_fail_rate"]
    lines.append(
        f"Post-merge fail rate: {pm['rate']:.1%} ({pm['failed']}/{pm['merged']}) "
        f"elite={'yes' if pm['elite'] else 'no'}"
    )
    return "\n".join(lines)


def append_metrics(path: str, summary: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", required=True, help="JSON file: list of events")
    ap.add_argument("--window-days", type=float, default=7.0)
    ap.add_argument("--append", default=None, help="append summary JSONL here")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    with open(args.events, encoding="utf-8") as handle:
        events = json.load(handle)
    if not isinstance(events, list):
        print("events file must be a JSON list", file=sys.stderr)
        return 1
    summary = summarize(events, window_days=args.window_days)
    if args.append:
        append_metrics(args.append, summary)
    if args.report or not args.append:
        print(format_report(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
