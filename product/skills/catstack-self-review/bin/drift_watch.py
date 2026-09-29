#!/usr/bin/env python3
"""Drift watch for catstack-on-Muse: the backstop behind the per-turn self-review.

Runs every 30 minutes via cron. Stays silent unless something needs attention:
  1. The self-review adapter or hook registry is broken (import/registry failure).
  2. A session's latest ledger entry is a STOP with no clean re-run after it --
     either a stop fired and the work stalled, or the agent acted anyway.
  3. Stop rate over the last 24h is anomalously high (possible drift wave).

Exit 0 and no output when there is nothing to say.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

CACHE = os.path.join(os.path.expanduser("~"), ".cache")
LEDGER = os.path.join(CACHE, "catstack-muse-review", "ledger.jsonl")
ADAPTER = os.path.join(
    os.path.expanduser("~"), "workspace", "skills",
    "catstack-self-review", "bin", "muse_self_review.py",
)
WINDOW_SECONDS = 24 * 3600
STOP_RATE_ALERT = 0.5  # >50% of reviews stopping in 24h is a drift wave
MIN_REVIEWS_FOR_RATE = 5


def _read_ledger() -> list[dict]:
    rows: list[dict] = []
    try:
        with open(LEDGER, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def main() -> int:
    problems: list[str] = []

    # 1. Adapter + registry health: run the fast path against a trivial review.
    probe = {
        "session_id": "muse-drift-watch-probe",
        "draft": "ok",
        "tool_calls": [],
        "cwd": os.getcwd(),
        "hooks": ["diu-stop"],
    }
    try:
        proc = subprocess.run(
            [sys.executable, ADAPTER],
            input=json.dumps(probe),
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode not in (0, 1, 2) or "self-review" not in proc.stdout:
            problems.append(
                f"self-review adapter unhealthy: exit={proc.returncode} "
                f"stderr={proc.stderr.strip()[:300]}"
            )
    except Exception as exc:
        problems.append(f"self-review adapter failed to run: {exc}")

    # 2+3. Ledger analysis.
    rows = _read_ledger()
    now = time.time()
    real = [r for r in rows
            if not str(r.get("session_id", "")).startswith(("muse-proof", "muse-drift-watch-probe"))]
    recent = [r for r in real if now - _ts(r.get("ts", "")) < WINDOW_SECONDS]

    latest_by_session: dict[str, dict] = {}
    for row in real:
        latest_by_session[row.get("session_id", "?")] = row
    for sid, row in sorted(latest_by_session.items()):
        if row.get("exit") == 2:
            problems.append(
                f"session {sid}: latest self-review is a STOP with no clean "
                f"re-run after it ({row.get('stops')} stop finding(s), "
                f"{row.get('ts')}). Either work stalled or the agent acted anyway."
            )

    if len(recent) >= MIN_REVIEWS_FOR_RATE:
        stopped = sum(1 for r in recent if r.get("exit") == 2)
        rate = stopped / len(recent)
        if rate > STOP_RATE_ALERT:
            problems.append(
                f"stop rate {stopped}/{len(recent)} ({rate:.0%}) over the last "
                f"24h exceeds {STOP_RATE_ALERT:.0%} -- possible drift wave; "
                f"check what keeps getting stopped."
            )

    if problems:
        print("catstack-muse drift watch: attention needed")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    return 0


def _ts(value: str) -> float:
    try:
        return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
