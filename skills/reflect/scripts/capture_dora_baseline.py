#!/usr/bin/env python3
"""Capture a commit-safe DORA-for-agents baseline (aggregates only).

Runs collect_dora_events for 7d and 30d windows, summarizes with dora_ai,
and writes skills/reflect/baselines/dora-ai.json — no transcript paths.

Usage:
    python3 skills/reflect/scripts/capture_dora_baseline.py
    python3 skills/reflect/scripts/capture_dora_baseline.py --out PATH
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import collect_dora_events  # noqa: E402
import dora_ai  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "skills", "reflect", "baselines", "dora-ai.json")

IMPROVEMENT_DIRECTION = {
    "lead_pickup.median_seconds": "lower",
    "mttr.median_seconds": "lower",
    "rework_rate.rate": "lower",
    "deploy_frequency.per_day": "higher",
}


def capture(*, max_sessions: int = 80) -> dict:
    windows = {}
    for label, days in (("7d", 7.0), ("30d", 30.0)):
        hours = days * 24.0
        print(f"=== capturing {label} ({hours}h) ===", file=sys.stderr)
        events = collect_dora_events.collect(
            hours=hours,
            skip_gh=False,
            skip_sessions=False,
            max_sessions=max_sessions,
        )
        summary = dora_ai.summarize(events, window_days=days)
        windows[label] = collect_dora_events.public_summary(
            summary, window_days=days, hours=hours
        )
        print(dora_ai.format_report(summary), file=sys.stderr)
    return {
        "version": 2,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": (
            "Aggregates only — no transcript paths. Version 2: rework includes "
            "session thrash + git path-churn (fix-forward); post-merge fail is "
            "reported but not gated. Update only when every comparable metric "
            "is equal or improved (check_dora_baseline.py --check-update). "
            "Goal: lead/MTTR/rework go down WoW/MoM; deploy frequency goes up. "
            "Repos: session workspace/cwd plus CATSTACK_DORA_GIT_ROOTS."
        ),
        "improvement_direction": IMPROVEMENT_DIRECTION,
        "windows": windows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-sessions", type=int, default=80)
    args = ap.parse_args(argv)
    payload = capture(max_sessions=args.max_sessions)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
