#!/usr/bin/env python3
"""Build a live Datadog Logs Explorer link and a reconciliation table for one number.

Pure functions, no network, read-only. The agent runs the Datadog queries; this
script writes the link (time window baked in) and the table the agent fills in.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

DEFAULT_HOST = os.environ.get("DD_SITE_HOST", "app.datadoghq.com")
_REL_RE = re.compile(r"^(\d+)([mhdw])$")
_UNIT = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
COLUMNS = ("source", "window", "numerator", "denominator", "user-seen value", "delta")


def parse_time(text: str, now: datetime) -> datetime:
    """ISO timestamp (naive means UTC), "now", or a relative age such as 24h, 7d, 90m, 2w."""
    text = text.strip()
    if text == "now":
        return now
    rel = _REL_RE.match(text)
    if rel:
        n = int(rel.group(1))
        if n < 1:
            raise ValueError(f"relative time must be at least 1: {text!r}")
        return now - timedelta(**{_UNIT[rel.group(2)]: n})
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"cannot parse time {text!r}: use ISO (2026-10-01T00:00:00Z) or relative (24h, 7d)")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_window(start: str, end: str, now: datetime) -> tuple[datetime, datetime]:
    lo, hi = parse_time(start, now), parse_time(end, now)
    if lo >= hi:
        raise ValueError(f"window start {lo.isoformat()} is not before end {hi.isoformat()}")
    return lo, hi


def to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def logs_url(query: str, lo: datetime, hi: datetime, host: str = DEFAULT_HOST) -> str:
    if not query.strip():
        raise ValueError("query is empty")
    return f"https://{host}/logs?query={quote(query, safe='')}&from_ts={to_ms(lo)}&to_ts={to_ms(hi)}&live=false"


def reconciliation_table(source: str, lo: datetime, hi: datetime, seen: str = "") -> str:
    window = f"{lo.isoformat()} to {hi.isoformat()}"
    row = (source, window, "", "", seen, "")
    return "\n".join(
        [
            "| " + " | ".join(COLUMNS) + " |",
            "|" + "|".join("---" for _ in COLUMNS) + "|",
            "| " + " | ".join(row) + " |",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("query", help="Datadog logs query string")
    p.add_argument("--from", dest="start", required=True, help="ISO time or relative age (24h, 7d)")
    p.add_argument("--to", dest="end", default="now", help="ISO time, relative age, or now")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--source", default="", help="name of the dashboard tile, saved query or sheet")
    p.add_argument("--seen", default="", help="the value the user sees")
    return p


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = now or datetime.now(timezone.utc)
    try:
        lo, hi = parse_window(args.start, args.end, now)
        url = logs_url(args.query, lo, hi, args.host)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Logs Explorer: {url}\n")
    print(reconciliation_table(args.source or args.query, lo, hi, args.seen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
