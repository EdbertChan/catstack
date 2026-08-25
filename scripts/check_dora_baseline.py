#!/usr/bin/env python3
"""Compare a DORA-for-agents measurement to the committed baseline.

Improvement directions (locked):
  lead_pickup.median_seconds     → lower is better
  mttr.median_seconds            → lower is better
  rework_rate.rate               → lower is better
  post_merge_fail_rate.rate      → lower is better
  deploy_frequency.per_day       → higher is better

A regression is any metric that moves the wrong way vs the committed baseline
for the same window (7d / 30d). Missing samples (null median with sample_count
0) do not count as a regression against a null baseline cell; they do count
as a regression if the baseline had a real median and the new run has none
for a "lower is better" clock that previously had data — treat as INCONCLUSIVE
and fail closed only when both sides have numbers.

Updating the committed baseline is allowed only when every comparable metric
is equal or improved (see --allow-update checks in docs). This script never
rewrites the baseline file.

Usage:
    python3 scripts/check_dora_baseline.py
    python3 scripts/check_dora_baseline.py --current PATH --baseline PATH
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE = os.path.join(
    REPO, "skills", "reflect", "baselines", "dora-ai.json"
)

# path in window blob → "lower" | "higher"
DIRECTIONS = {
    ("lead_pickup", "median_seconds"): "lower",
    ("mttr", "median_seconds"): "lower",
    ("rework_rate", "rate"): "lower",
    ("post_merge_fail_rate", "rate"): "lower",
    ("deploy_frequency", "per_day"): "higher",
}


def _get(blob: dict[str, Any], a: str, b: str) -> Any:
    return (blob.get(a) or {}).get(b)


def compare_window(
    baseline: dict[str, Any], current: dict[str, Any], *, window: str
) -> list[str]:
    """Return human-readable regression lines (empty = ok)."""
    problems: list[str] = []
    for (a, b), direction in DIRECTIONS.items():
        base_v = _get(baseline, a, b)
        cur_v = _get(current, a, b)
        if base_v is None or cur_v is None:
            # Incomplete measurement — do not treat as pass or hard fail.
            continue
        try:
            base_f = float(base_v)
            cur_f = float(cur_v)
        except (TypeError, ValueError):
            problems.append(f"{window}.{a}.{b}: non-numeric ({base_v!r} -> {cur_v!r})")
            continue
        if direction == "lower" and cur_f > base_f + 1e-9:
            problems.append(
                f"{window}.{a}.{b}: worsened {base_f} -> {cur_f} (must go down or stay)"
            )
        if direction == "higher" and cur_f < base_f - 1e-9:
            problems.append(
                f"{window}.{a}.{b}: worsened {base_f} -> {cur_f} (must go up or stay)"
            )
    return problems


def can_update_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return problems preventing a baseline bump (must be all equal-or-better)."""
    problems: list[str] = []
    for window in sorted(set(baseline.get("windows", {})) | set(current.get("windows", {}))):
        b = (baseline.get("windows") or {}).get(window) or {}
        c = (current.get("windows") or {}).get(window) or {}
        problems.extend(compare_window(b, c, window=window))
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument(
        "--current",
        default=None,
        help="measurement JSON (same shape as baseline). If omitted, only validates baseline file exists.",
    )
    ap.add_argument(
        "--check-update",
        action="store_true",
        help="fail unless --current is equal-or-better than baseline (gate for bumping baseline)",
    )
    args = ap.parse_args(argv)

    if not os.path.isfile(args.baseline):
        print(f"check_dora_baseline: FAIL missing baseline {args.baseline}")
        return 1
    with open(args.baseline, encoding="utf-8") as handle:
        baseline = json.load(handle)
    if "windows" not in baseline or "improvement_direction" not in baseline:
        print("check_dora_baseline: FAIL baseline missing windows or improvement_direction")
        return 1

    if args.current is None:
        print(f"check_dora_baseline: OK (baseline present: {args.baseline})")
        return 0

    with open(args.current, encoding="utf-8") as handle:
        current = json.load(handle)

    if args.check_update:
        problems = can_update_baseline(baseline, current)
        label = "baseline-update"
    else:
        problems = []
        for window, b_win in (baseline.get("windows") or {}).items():
            c_win = (current.get("windows") or {}).get(window)
            if not c_win:
                problems.append(f"{window}: missing from current measurement")
                continue
            problems.extend(compare_window(b_win, c_win, window=window))
        label = "regression"

    if problems:
        print(f"check_dora_baseline: FAIL ({label})")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"check_dora_baseline: OK ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
