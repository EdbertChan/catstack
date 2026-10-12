#!/usr/bin/env python3
"""Build the Datadog queries and the report for one CI job's step timing.

The Datadog connector is only reachable from the agent, so this script does the
two parts that must be identical on every run: write the query text (`queries`,
`timeline`) and turn the query result into a table (`report`). `context` reads
GitLab (read-only) to show what a job waits for and which prerequisite finished last.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote

DEFAULT_HOST = "app.datadoghq.com"
DEFAULT_GITLAB = "https://gitlab.example.com"
DEFAULT_PROJECT = "group/app"
TOKEN_ENV = "GITLAB_TOKEN"
# GitLab job names look like "Build vm (dev)": letters, digits, space, ( ) . _ : / -
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

NEEDS_QUERY = (
    "query($path: ID!, $iid: ID!) { project(fullPath: $path) { pipeline(iid: $iid) { "
    "stages { nodes { groups { nodes { jobs { nodes { name needs { nodes { name } } } } } } } } } } }"
)


def parse_needs(graphql_json: dict, job: str) -> list[str]:
    """Names the job needs, from the stages/groups/jobs GraphQL shape. Job absent -> error."""
    if graphql_json.get("errors"):
        raise ValueError(f"GitLab GraphQL returned errors: {graphql_json['errors']}")
    pipeline = ((graphql_json.get("data") or {}).get("project") or {}).get("pipeline")
    if not pipeline:
        raise ValueError("GraphQL reply has no project.pipeline (wrong project or pipeline number)")
    for stage in (pipeline.get("stages") or {}).get("nodes") or []:
        for group in (stage.get("groups") or {}).get("nodes") or []:
            for j in (group.get("jobs") or {}).get("nodes") or []:
                if j.get("name") == job:
                    names = [n["name"] for n in (j.get("needs") or {}).get("nodes") or []]
                    return list(dict.fromkeys(names))
    raise ValueError(f"job {job!r} not found in the pipeline's stages")


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _latest(jobs: list[dict], name: str, key: str) -> dict | None:
    """Latest attempt of one job name by `key` (retries share a name)."""
    best, best_t = None, None
    for j in jobs:
        t = _ts(j.get(key)) if j.get("name") == name else None
        if t is not None and (best_t is None or t > best_t):
            best, best_t = j, t
    return best


def summarize(job: str, needs: list[str], jobs_by_pipeline: dict) -> dict:
    """Per pipeline: which needed job finished last and how long the job then waited.

    A needed job that is absent or unfinished in a pipeline is skipped (optional needs).
    A pipeline where the job never started, or no need finished, yields no row.
    """
    rows, last_counts, skipped = [], {}, {}
    for pid, jobs in jobs_by_pipeline.items():
        me = _latest(jobs, job, "started_at")
        if me is None:
            continue
        finishers = []
        for need in needs:
            n = _latest(jobs, need, "finished_at")
            if n is None:
                skipped[need] = skipped.get(need, 0) + 1
            else:
                finishers.append((_ts(n["finished_at"]), need))
        if not finishers:
            continue
        fin_t, fin_name = max(finishers)
        gap = (_ts(me["started_at"]) - fin_t).total_seconds()
        rows.append({
            "pipeline": pid,
            "last_finisher": fin_name,
            "gap_s": gap,
            "queued_s": me.get("queued_duration"),
        })
        last_counts[fin_name] = last_counts.get(fin_name, 0) + 1
    gaps = [r["gap_s"] for r in rows]
    return {
        "job": job,
        "needs": list(needs),
        "rows": rows,
        "last_counts": dict(sorted(last_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "skipped": skipped,
        "median_gap_s": statistics.median(gaps) if gaps else None,
        "max_gap_s": max(gaps) if gaps else None,
    }


def render_context(summary: dict, base_url: str = DEFAULT_GITLAB, project: str = DEFAULT_PROJECT) -> str:
    if not summary["rows"]:
        raise ValueError("no pipeline had both the job started and a needed job finished")
    out = [f"## {summary['job']}: what it waits for", ""]
    out.append("Needs: " + (", ".join(f"`{n}`" for n in summary["needs"]) or "none listed"))
    n = len(summary["rows"])
    out += ["", f"Last needed job to finish, over {n} pipeline(s):", "",
            "| Needed job | Finished last | Share |", "|---|---|---|"]
    for name, cnt in summary["last_counts"].items():
        out.append(f"| {name} | {cnt} | {cnt / n:.0%} |")
    out += ["", "Gap = last needed job finished -> this job started.",
            f"- Median gap: {summary['median_gap_s']:.0f} s",
            f"- Maximum gap: {summary['max_gap_s']:.0f} s", "",
            "| Pipeline | Last finisher | Gap (s) | Queued (s) |", "|---|---|---|---|"]
    for r in summary["rows"]:
        url = f"{base_url}/{project}/-/pipelines/{r['pipeline']}"
        q = "" if r["queued_s"] is None else f"{float(r['queued_s']):.0f}"
        out.append(f"| [{r['pipeline']}]({url}) | {r['last_finisher']} | {r['gap_s']:.0f} | {q} |")
    out += ["", "Needs listed but absent (or unfinished) in a pipeline are skipped; they may be optional needs."]
    if summary["skipped"]:
        out.append("Skipped: " + ", ".join(f"{k} ({v}x)" for k, v in sorted(summary["skipped"].items())))
    return "\n".join(out)


# --- thin network reader (read-only GitLab) ---------------------------------


def http_get_json(url: str, token: str, body: dict | None = None):
    """GET (or POST for GraphQL, which is a read-only query). Errors never echo the token."""
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise OSError(f"GitLab request failed: HTTP {e.code} for {url}") from None
    except urllib.error.URLError as e:
        raise OSError(f"GitLab request failed: {e.reason} for {url}") from None


def _paged(url: str, token: str, get=http_get_json):
    page = 1
    while True:
        batch = get(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}", token)
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def _pipelines_from_job_ids(api, job, job_ids, token, get):
    """Resolve known job numbers to their pipelines. A job number whose name differs is an error."""
    found = {}
    for jid in job_ids:
        j = get(f"{api}/jobs/{int(jid)}", token)
        if j.get("name") != job:
            raise ValueError(f"job {int(jid)} is named {j.get('name')!r}, not {job!r}")
        pl = j["pipeline"]
        found[pl["id"]] = pl["iid"]
    return found


def fetch_context_inputs(host, project, job, n, token, scan_limit=200, get=http_get_json, job_ids=None):
    """Return (needs, jobs_by_pipeline) for pipelines containing `job`.

    With job_ids, those jobs' pipelines are used directly. Without, the newest finished pipelines
    are scanned, which can miss the job on a busy project."""
    api = f"{host}/api/v4/projects/{quote(project, safe='')}"
    if job_ids:
        pipes = _pipelines_from_job_ids(api, job, job_ids, token, get)
        jobs_by_pipeline = {pid: list(_paged(f"{api}/pipelines/{pid}/jobs", token, get)) for pid in pipes}
        newest_iid = max(pipes.values())
        reply = get(f"{host}/api/graphql", token,
                    {"query": NEEDS_QUERY, "variables": {"path": project, "iid": str(newest_iid)}})
        return parse_needs(reply, job), jobs_by_pipeline
    jobs_by_pipeline, newest_iid, scanned = {}, None, 0
    for p in _paged(f"{api}/pipelines?scope=finished&order_by=id&sort=desc", token, get):
        scanned += 1
        if scanned > scan_limit:
            break
        jobs = list(_paged(f"{api}/pipelines/{p['id']}/jobs", token, get))
        if not any(j.get("name") == job for j in jobs):
            continue
        jobs_by_pipeline[p["id"]] = jobs
        if newest_iid is None:
            newest_iid = p["iid"]
        if len(jobs_by_pipeline) >= n:
            break
    if not jobs_by_pipeline:
        raise ValueError(f"no job named {job!r} in the {scanned} newest finished pipelines; pass --job-ids with recent job numbers from Datadog")
    reply = get(f"{host}/api/graphql", token,
                {"query": NEEDS_QUERY, "variables": {"path": project, "iid": str(newest_iid)}})
    return parse_needs(reply, job), jobs_by_pipeline


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
    pc = sub.add_parser("context", help="what the job waits for and which need finished last (GitLab, read-only)")
    pc.add_argument("--job", required=True)
    pc.add_argument("--pipelines", type=int, default=10)
    pc.add_argument("--gitlab-host", default=DEFAULT_GITLAB)
    pc.add_argument("--project", default=DEFAULT_PROJECT)
    pc.add_argument("--job-ids", default="", help="comma-separated recent job numbers for this job (from Datadog); preferred")
    a = ap.parse_args(argv)
    if a.cmd == "context":
        token = os.environ.get(TOKEN_ENV)
        if not token:
            print(f"error: {TOKEN_ENV} is not set; export a GitLab read_api token", file=sys.stderr)
            return 2
        try:
            check_job(a.job)
            if a.pipelines < 1:
                raise ValueError("--pipelines must be at least 1")
            host = a.gitlab_host.rstrip("/")
            ids = [int(x) for x in a.job_ids.split(",") if x.strip()]
            needs, by_pipeline = fetch_context_inputs(host, a.project, a.job, a.pipelines, token, job_ids=ids)
            print(render_context(summarize(a.job, needs, by_pipeline), host, a.project))
        except (ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
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
