#!/usr/bin/env python3
"""Gate the hook dispatcher canary against the pre-dispatcher baseline.

This script is read-only: it reads the hook metrics JSONL, folds the same
scorecard rows as engine/hooks/_runner/report.py, prints the comparison, and
exits non-zero when the SubagentStop canary is not safe to widen.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "engine" / "hooks" / "_runner"
sys.path.insert(0, str(RUNNER))

import report as hook_report

MATERIAL_SPOKE_DROP = 0.10


def _row_by_phase_event(scorecard: dict[str, Any], phase: str, event: str) -> dict[str, Any] | None:
    for row in scorecard["scorecard"]:
        if row.get("phase") == phase and row.get("event") == event:
            return row
    return None


def _fmt_rate(value: object) -> str:
    return "-" if not isinstance(value, (int, float)) else f"{value:.2f}"


def _bad_rate_regressed(name: str, baseline: float, post: float) -> str | None:
    if baseline > 0 and post >= baseline:
        return f"{name} did not improve: before={baseline:.2f} after={post:.2f}"
    if baseline == 0 and post > 0:
        return f"{name} regressed from zero: before={baseline:.2f} after={post:.2f}"
    return None


def evaluate_canary(
    scorecard: dict[str, Any],
    *,
    event: str = "SubagentStop",
    material_spoke_drop: float = MATERIAL_SPOKE_DROP,
) -> tuple[int, list[str]]:
    before = _row_by_phase_event(scorecard, "before", event)
    after = _row_by_phase_event(scorecard, "after", event)
    messages: list[str] = []
    if before is None:
        messages.append(f"unchecked: no pre-dispatcher baseline rows for {event}")
    if after is None:
        messages.append(f"unchecked: no post-dispatcher canary rows for {event}")
    if messages:
        return 2, messages

    before_spoke = float(before["spoke_rate"])
    after_spoke = float(after["spoke_rate"])
    spoke_drop = before_spoke - after_spoke
    if spoke_drop >= material_spoke_drop:
        messages.append(
            f"spoke-rate fell materially for {event}: before={before_spoke:.2f} "
            f"after={after_spoke:.2f} drop={spoke_drop:.2f}"
        )

    for name, key in (("timeout rate", "timeout_rate"), ("crash rate", "crash_rate")):
        problem = _bad_rate_regressed(name, float(before[key]), float(after[key]))
        if problem is not None:
            messages.append(problem)

    if messages:
        return 1, messages
    messages.append(
        f"PASS {event}: spoke-rate before={_fmt_rate(before['spoke_rate'])} "
        f"after={_fmt_rate(after['spoke_rate'])}; timeout before={_fmt_rate(before['timeout_rate'])} "
        f"after={_fmt_rate(after['timeout_rate'])}; crash before={_fmt_rate(before['crash_rate'])} "
        f"after={_fmt_rate(after['crash_rate'])}"
    )
    return 0, messages


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-window", choices=("pre-dispatcher",), required=True)
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--event", default="SubagentStop")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.days <= 0:
        print("--days must be positive", file=sys.stderr)
        return 2
    threshold = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows, malformed, error = hook_report.read_rows(hook_report.metrics_path(), threshold)
    if error is not None:
        print(error)
        return 2
    scorecard = hook_report.build_scorecard(rows or [], malformed, [])
    code, messages = evaluate_canary(scorecard, event=args.event)
    if args.json:
        print(json.dumps({"code": code, "messages": messages, **scorecard}, sort_keys=True))
    else:
        print(hook_report.format_scorecard_table(scorecard), end="")
        for message in messages:
            print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
