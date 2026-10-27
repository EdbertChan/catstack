---
name: trace-ci-job
description: >-
  Fixed read-only procedure for "where is this CI job declared". Use when asked
  what line declares a GitLab job, what triggers it or what it waits for, what
  a job step maps to in code, what a !reference or extends resolves to, or how
  the dev and prod variants of a job differ.
---

# trace-ci-job

One runbook for any GitLab CI job. The agent reads YAML at one pinned commit,
cites file:line for every hop, and opens the cited lines for the user. It never
edits YAML and never reads the moving working tree.

`<skill>` is this skill's folder. Read data over the GitLab API or `git show`,
never by driving a browser. Chrome is only for showing the user the result.

## Why this skill exists

GitLab merges `extends` and `!reference` away before any API shows the job, so
the merged-config view has no line numbers for where a value came from. This
skill reads the raw YAML and keeps the lines.

For the different question "does this job run in scenario X", use a tool that
renders GitLab's merged config (the CI lint API, or a repo's own config
inspector). It answers that, but it cannot give file:line for inherited values.

## Steps

1. Pin a commit. Use the SHA the user's pipeline ran on (`git rev-parse` or the
   pipeline's `sha`). A branch name is refused because it moves.
2. Resolve the name. The user's name ("Build App (dev)") may differ from the
   YAML key. `trace` resolves case and punctuation, prints
   `resolved 'X' -> 'Y'`, and on no match exits 2 listing close matches. Show
   those and ask; do not guess.
3. Trace the job:
   `python3 <skill>/scripts/trace_ci_job.py trace --job "<name>" --sha <sha> --follow-scripts`
   Add `--repo <clone>` to read with `git show SHA:path`; without it the script
   uses the files API with `GITLAB_TOKEN`, `GITLAB_HOST` (default
   `https://gitlab.com`) and `GITLAB_PROJECT` (or `--gitlab-host` / `--project`).
   When the clone lives on another machine, run the script there. Output is one hop per line:
   job definition, `extends`, `!reference` and its target, `rules:if` and
   `rules:changes`, `stage`, `trigger`, and the script lines.
4. Edges. `needs-up` hops are what the job waits for; `needs-down` hops are the
   jobs that wait for it. Each cites the YAML line that creates the edge. Say
   which edge is the one the user asked about, with its line.
5. Code. `--follow-scripts` reads each `.sh` a script line runs at the same
   SHA and lists the functions those lines call (`shell`, `shell-fn` hops).
   Open the function and quote the lines the user asked about.
6. Proof it runs. Get recent job ids for the job name from Datadog, then:
   `python3 <skill>/scripts/trace_ci_job.py proof --job "<exact name>" --job-ids <ids>`
   Report the job log URL and duration it prints.
7. Dev vs prod, when both exist:
   `python3 <skill>/scripts/trace_ci_job.py diff --job "<dev>" --other "<prod>" --sha <sha>`
   Every differing key shows its value and file:line on each side.
8. Show the user. Re-run step 3 with `--open` so every cited file opens in
   their Google Chrome at `#Lx-Ly`. Opening is the deliverable; a printed link
   is not. The ask-to-scope hook gates browser tools, so ask once before this
   step.

## Limits to say out loud

- Remote, project, template and wildcard includes are not followed; the script
  prints a `note:` for each. Name the gap in the answer.
- A job with a `!reference` or `extends` target that does not exist is an
  error, not a silent skip.
- `needs` with no entry means the job waits for every earlier stage; the trace
  says so.
