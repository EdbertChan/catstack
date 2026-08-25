#!/usr/bin/env python3
"""Regenerate dora-ai-report.md from a measurement + history."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))))

DEFAULT_MEASUREMENT = os.path.join(REPO, "engine", "skills", "reflect", "baselines", "dora-ai.json")
DEFAULT_OUT = os.path.join(REPO, "engine", "skills", "reflect", "baselines", "dora-ai-report.md")


def _fmt_pct(rate: float | None) -> str:
    if rate is None:
        return "n/a"
    return f"{rate * 100:.1f}%"


def _fmt_duration(seconds: Any) -> str:
    """Human duration: 45s, 12m, 2.1h, 1d 3h — never scientific notation."""
    if seconds is None:
        return "n/a"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "n/a"
    if s < 0:
        s = 0.0
    if s < 60:
        return f"{int(round(s))}s"
    if s < 3600:
        mins = s / 60.0
        if abs(mins - round(mins)) < 0.05:
            return f"{int(round(mins))}m"
        return f"{mins:.1f}m"
    if s < 86400:
        hours = s / 3600.0
        if abs(hours - round(hours)) < 0.05:
            return f"{int(round(hours))}h"
        return f"{hours:.1f}h"
    days = int(s // 86400)
    rem_h = (s % 86400) / 3600.0
    if rem_h < 0.05:
        return f"{days}d"
    return f"{days}d {rem_h:.0f}h"


def _fmt_num(val: Any, *, suffix: str = "") -> str:
    if val is None:
        return "n/a"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "n/a"
    if abs(f - round(f)) < 1e-9:
        return f"{int(round(f))}{suffix}"
    return f"{f:.2f}".rstrip("0").rstrip(".") + suffix


def _window_table(win: dict[str, Any], label: str) -> str:
    lead = win.get("lead_pickup") or {}
    deploy = win.get("deploy_frequency") or {}
    mttr = win.get("mttr") or {}
    rework = win.get("rework_rate") or {}
    post = win.get("post_merge_fail_rate") or {}
    return f"""### {label}

| Metric | Value | Notes |
| --- | --- | --- |
| Lead (median) | **{_fmt_duration(lead.get("median_seconds"))}** | Sample count: {lead.get("sample_count", "n/a")}. Often synthetic when transcripts lack wall clocks. |
| Deploy | **~{_fmt_num(deploy.get("per_day"))} / day** ({deploy.get("merged", "n/a")} merges) | Uncapped local git first-parent on allowlisted clones (Invoker + catstack); optional gh search with 1000-hit bisect. |
| MTTR (median) | **{_fmt_duration(mttr.get("median_seconds"))}** | Sample count: {mttr.get("sample_count", "n/a")}. Time from thrash → verify. |
| Rework | **{_fmt_pct(rework.get("rate"))}** ({rework.get("failed", "?")} / {rework.get("started", "?")}) | **Main number to drive down.** Elite &lt; 15%. |
| Post-merge fail | **{_fmt_pct(post.get("rate"))}** | Reported only — fix-forward; not gated. |
"""


def render_report(measurement: dict[str, Any]) -> str:
    captured = measurement.get("captured_at") or "unknown"
    version = measurement.get("version") or "?"
    windows = measurement.get("windows") or {}
    w7 = windows.get("7d") or {}
    w30 = windows.get("30d") or {}
    return f"""# DORA-for-agents baseline report (v{version})

**Captured:** {captured}  
**File:** [`dora-ai.json`](./dora-ai.json) · **History:** [`dora-ai-history.json`](./dora-ai-history.json)  
**Goal:** week over week / month over month, bad clocks go **down**; deploy frequency goes **up**. Do not commit a worse baseline.

## Trends

Rework should fall over time (green dashed line = elite 15%).

![Rework 7d](charts/rework-7d.svg)

![Rework 30d](charts/rework-30d.svg)

![Deploy 7d](charts/deploy-7d.svg)

![MTTR 7d](charts/mttr-7d.svg)

## What these numbers mean (plain English)

| Clock | Question it answers | Better when |
| --- | --- | --- |
| **Lead** | After you say “go,” how fast does the agent start editing? | Lower |
| **Deploy frequency** | How many PRs merge per day? | Higher (also rises when you work more) |
| **MTTR** | After thrash, how long until a verify-ish recovery? | Lower |
| **Rework** | Of work we started, how often did we thrash or rewrite? | Lower |
| **Post-merge fail** | Reverts / hotfixes after merge | *Reported only* — we fix forward, so this stays ~0 and is **not gated** |

**Elite bars (targets, not the baseline itself):** lead &lt; 15m, deploy ≥ 2/day, MTTR &lt; 1h, rework &lt; 15%.

### Where deploy frequency comes from

Count of **shipped changes** in the window ÷ days:

1. **Local git** first-parent commits on `main` for allowlisted clones (Invoker +
   catstack) — works offline and for backfill (no API rate limit)
2. Optional supplement: date-scoped `gh search` on the same repos

So Invoker merges show up. Older chart zeros were from rate-limited GitHub
search + “newest 100 only” listing — fixed.

## Committed snapshot

{_window_table(w7, "Last 7 days")}

{_window_table(w30, "Last 30 days")}

## How rework is counted (v2)

A started execution “fails” (counts in the numerator) if **either**:

1. **Session thrash** — same flags as `reflect-on-thrash` (including `intervention-must-automate`), or
2. **Git path-churn** — ≥3 commits within 24h that overlap the same path(s), optionally paired to a session via Write/Edit paths + workspace/cwd / `CATSTACK_DORA_GIT_ROOTS`.

```text
rework_rate = failed_executions / started_executions
```

## Refresh (weekly job)

```bash
python3 skills/reflect/scripts/publish_dora_snapshot.py --dry-run
# opt-in schedule: ./install.sh --with-dora-snapshot
```

History always records the measurement. `dora-ai.json` updates only when every gated metric is equal or better (`check_dora_baseline.py --check-update`).
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measurement", default=DEFAULT_MEASUREMENT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    with open(args.measurement, encoding="utf-8") as handle:
        measurement = json.load(handle)
    text = render_report(measurement)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
