#!/usr/bin/env python3
"""Backfill dora-ai-history.json with weekly as-of captures, then render charts.

Usage:
    python3 skills/reflect/scripts/backfill_dora_history.py --weeks 13
    python3 skills/reflect/scripts/backfill_dora_history.py --weeks 13 --max-sessions 20
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import capture_dora_baseline  # noqa: E402
import dora_history  # noqa: E402
import render_dora_charts  # noqa: E402
import render_dora_report  # noqa: E402

HISTORY_PATH = os.path.join(REPO, "skills", "reflect", "baselines", "dora-ai-history.json")
CHARTS_DIR = os.path.join(REPO, "skills", "reflect", "baselines", "charts")
BASELINE_PATH = os.path.join(REPO, "skills", "reflect", "baselines", "dora-ai.json")
REPORT_PATH = os.path.join(REPO, "skills", "reflect", "baselines", "dora-ai-report.md")


def week_ends(*, weeks: int, end: datetime | None = None) -> list[datetime]:
    """UTC Mondays 12:00 going back `weeks` (oldest first), ending at/near end."""
    end = end or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    # Align to Monday 12:00 UTC of the week containing end.
    weekday = end.weekday()  # Mon=0
    this_monday = (end - timedelta(days=weekday)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    points = [this_monday - timedelta(weeks=i) for i in range(weeks)]
    points.reverse()
    return points


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weeks", type=int, default=13)
    ap.add_argument("--max-sessions", type=int, default=20)
    ap.add_argument(
        "--with-sessions",
        action="store_true",
        help="include session thrash (slower); default is git+gh only for backfill speed",
    )
    args = ap.parse_args(argv)

    history = {
        "version": 1,
        "notes": (
            "Weekly as-of backfill (git path-churn + gh merges; sessions optional). "
            "No transcript paths."
        ),
        "points": [],
    }
    for as_of in week_ends(weeks=args.weeks):
        print(f"\n######## backfill as_of={as_of.isoformat()} ########", file=sys.stderr)
        measurement = capture_dora_baseline.capture(
            max_sessions=args.max_sessions,
            as_of=as_of,
            skip_sessions=not args.with_sessions,
        )
        point = dora_history.snapshot_from_measurement(measurement)
        history, _ = dora_history.append_point(history, point, replace_same_week=True)
        rework = (point.get("windows") or {}).get("7d", {}).get("rework_rate", {}).get("rate")
        deploy = (
            (point.get("windows") or {}).get("7d", {}).get("deploy_frequency", {}).get("per_day")
        )
        print(f"  -> rework7d={rework} deploy7d={deploy}", file=sys.stderr)

    dora_history.save_history(HISTORY_PATH, history)
    render_dora_charts.render_all(history, CHARTS_DIR)
    # Keep committed baseline file; refresh report tables from it, charts from history.
    import json

    with open(BASELINE_PATH, encoding="utf-8") as handle:
        baseline = json.load(handle)
    # Prefer latest history point for report snapshot numbers if present.
    if history["points"]:
        latest = history["points"][-1]
        # Merge latest window rates into a display measurement for the report.
        display = dict(baseline)
        display["captured_at"] = latest.get("captured_at")
        # Rebuild minimal windows from latest point + baseline shape
        for label in ("7d", "30d"):
            if label not in display.get("windows", {}):
                continue
            src = (latest.get("windows") or {}).get(label) or {}
            for group, fields in (
                ("lead_pickup", ("median_seconds",)),
                ("mttr", ("median_seconds",)),
                ("rework_rate", ("rate", "started", "failed")),
                ("deploy_frequency", ("per_day", "merged")),
            ):
                if group in src:
                    display["windows"][label].setdefault(group, {})
                    for f in fields:
                        if f in src[group]:
                            display["windows"][label][group][f] = src[group][f]
        text = render_dora_report.render_report(display)
    else:
        text = render_dora_report.render_report(baseline)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"wrote {HISTORY_PATH} ({len(history['points'])} points)", file=sys.stderr)
    print(f"wrote charts + {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
