---
name: ci-job-timing
description: >-
  Repeatable per-step timing report for any GitLab CI job, from Datadog. Use
  when asked how long a CI job's steps take, where a slow job spends its time,
  or to compare the same job across dev/prod or across different jobs
  (for example "Build LAGVM (dev)", "xmm-image-packager (dev)").
---

# ci-job-timing

One recipe, any job. The job name and the number of days are the only inputs.

## Why it reads log text

Datadog CI Visibility has job-level events (`@ci.job.name`, `@duration` in
nanoseconds) but no step-level events. Step times come from `[CI_STEP]` log
lines written by the CI step wrapper. Lines from side-by-side tracks carry a
prefix (for example `[gvm]`, `[qssi]`) and Datadog does not split them into
fields, so the script reads the message text ("took N seconds") instead.

## Steps

0. Context first: why does the job start late? What does it wait for, and which
   prerequisite finished last? (`<skill>` is this skill's folder.)
   `python3 <skill>/scripts/ci_job_timing.py context --job "<exact job name>" --pipelines 10 --job-ids <ids>`
   Get `<ids>` (comma-separated) from Datadog first: `search_datadog_ci_pipeline_events`,
   `ci_level=job`, query `@ci.job.name:"<job>" @ci.status:success`, `limit=10`; use the
   `job_id` column. Scanning GitLab's pipeline list instead can miss the job on a busy project.
   This reads GitLab (read-only) with the token in `GITLAB_TOKEN`; without it the
   script prints an error and exits 2. Timing comes from GitLab, not Datadog,
   because Datadog job records have no pipeline number. Needs absent from a
   pipeline (optional needs) are skipped. Host and project default to
   `https://gitlab.rivianvw.io` and `core/firmware` (`--gitlab-host`, `--project`).
1. Build the query and its link:
   `python3 <skill>/scripts/ci_job_timing.py queries --job "<exact job name>" --days 3`
2. Run the printed steps query with the Datadog `ddsql_run_query` tool (from `now-<days>d`).
3. Save the TSV it returns to a file and render the table:
   `python3 <skill>/scripts/ci_job_timing.py report --job "<job>" --days 3 --tsv <file>`
4. For side-by-side steps, pick one `job_id` from a raw `[CI_STEP]` line and run
   `ci_job_timing.py timeline --job "<job>" --job-id <id>`. Read the start and end
   times there; never add step averages into a job time.
5. Optional job-level cross-check: `aggregate_datadog_ci_pipeline_events` with
   `ci_level=job`, query `@ci.job.name:"<job>"`, metric `@duration`.

## Read the table correctly

- `Runs` counts successful step lines only. A run that stopped early does not
  count in its later steps, so counts differ between steps.
- Averages with few runs (n under 10) are weak. Say the n.
- Steps can overlap, so the column is not a share of the job.
- Zero rows means a wrong job name or an empty window: the script errors, it
  never prints an empty table.
- A job whose steps do not log `[CI_STEP]` lines returns nothing; say that.
