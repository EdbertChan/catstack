#!/usr/bin/env python3
"""Build the Datadog queries and the report for one CI job's step timing.

The Datadog connector is only reachable from the agent, so this script does the
two parts that must be identical on every run: write the query text (`queries`,
`timeline`) and turn the query result into a table (`report`).
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from urllib.parse import quote

DEFAULT_HOST = "rivianvw.datadoghq.com"
_JOB_RE = re.compile(r"^[A-Za-z0-9 ()._:/\-]+$")


def check_job(job: str) -> str:
    if not job or not _JOB_RE.match(job):
        raise ValueError(f"job name has characters the query cannot carry safely: {job!r}")
    return job


def check_days(days: int) -> int:
    if not 1 <= days <= 30:
        raise ValueError(f"days must be 1-30, got {days}")
    return days


def _seconds_expr() -> str:
    return "CAST(SPLIT_PART(SPLIT_PART(message, 'took ', 2), ' seconds', 1) AS DECIMAL)"


def steps_sql(job: str, days: int) -> str:
    """One row per step: runs, average, min, max seconds. Reads message text, so
    lines prefixed [gvm]/[qssi] (which Datadog does not split into fields) count too."""
    check_job(job)
    check_days(days)
    flt = f'"[CI_STEP]" STEP_SUCCESS "[job={job}]"'
    sec = _seconds_expr()
    return (
        "SELECT SPLIT_PART(SPLIT_PART(message, 'Step: <', 2), '>', 1) AS step, "
        f"COUNT(*) AS runs, AVG({sec}) AS avg_s, MIN({sec}) AS min_s, MAX({sec}) AS max_s "
        f"FROM dd.logs(columns => ARRAY['message'], filter => '{flt}', "
        f"from_timestamp => NOW() - INTERVAL '{days} day', to_timestamp => NOW()) "
        "AS (message VARCHAR) GROUP BY SPLIT_PART(SPLIT_PART(message, 'Step: <', 2), '>', 1) "
        "ORDER BY avg_s DESC LIMIT 60"
    )


def timeline_sql(job: str, job_id: int, days: int) -> str:
    """Every step line of one run, oldest first, so side-by-side steps are visible."""
    check_job(job)
    check_days(days)
    flt = f'"[CI_STEP]" "[job_id={int(job_id)}]" "[job={job}]"'
    return (
        "SELECT timestamp, message "
        f"FROM dd.logs(columns => ARRAY['timestamp', 'message'], filter => '{flt}', "
        f"from_timestamp => NOW() - INTERVAL '{days} day', to_timestamp => NOW()) "
        "AS (timestamp TIMESTAMP, message VARCHAR) ORDER BY timestamp LIMIT 200"
    )


def link(sql: str, host: str = DEFAULT_HOST) -> str:
    return f"https://{host}/ddsql/editor?q={quote(sql, safe='')}"


def parse_tsv(text: str) -> list[dict]:
    """Parse the TSV block ddsql_run_query returns. Missing header or no rows -> error."""
    body = text
    m = re.search(r"<TSV_DATA>(.*?)</TSV_DATA>", text, re.S)
    if m:
        body = m.group(1)
    body = body.strip("\n")
    if not body.strip():
        raise ValueError("no rows: the query returned nothing (wrong job name, or no runs in the window)")
    rows = list(csv.DictReader(io.StringIO(body), delimiter="\t"))
    need = {"step", "runs", "avg_s", "min_s", "max_s"}
    if not rows or not need <= set(rows[0]):
        raise ValueError(f"unexpected columns, need {sorted(need)}; got {list(rows[0]) if rows else 'none'}")
    return rows


def report(job: str, days: int, rows: list[dict], url: str) -> str:
    out = [
        f"## {job}: step times, last {days} day(s)",
        "",
        "| Step | Runs | Avg (s) | Avg (min) | Fastest (s) | Slowest (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        avg = float(r["avg_s"])
        out.append(
            f"| {r['step']} | {int(float(r['runs']))} | {avg:.0f} | {avg / 60:.1f} "
            f"| {float(r['min_s']):.0f} | {float(r['max_s']):.0f} |"
        )
    out += [
        "",
        "Steps can run side by side, so do not add these up to a job time.",
        f"Query: {url}",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("queries", "report", "timeline"):
        p = sub.add_parser(name)
        p.add_argument("--job", required=True)
        p.add_argument("--days", type=int, default=3)
        p.add_argument("--host", default=DEFAULT_HOST)
        if name == "timeline":
            p.add_argument("--job-id", type=int, required=True)
        if name == "report":
            p.add_argument("--tsv", required=True, help="file holding the steps query result")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "queries":
            sql = steps_sql(a.job, a.days)
            print(f"-- steps query\n{sql}\n-- link\n{link(sql, a.host)}")
        elif a.cmd == "timeline":
            sql = timeline_sql(a.job, a.job_id, a.days)
            print(f"-- timeline query\n{sql}\n-- link\n{link(sql, a.host)}")
        else:
            rows = parse_tsv(open(a.tsv, encoding="utf-8").read())
            print(report(a.job, a.days, rows, link(steps_sql(a.job, a.days), a.host)))
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
