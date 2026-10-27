---
name: trace-number
description: >-
  Fixed read-only procedure for "where does this number come from". Use when
  asked where a dashboard tile, chart, sheet or memo number comes from, to
  prove it, to open the query behind it, or to check someone else's claim
  about a figure.
---

# trace-number

One runbook for any number. The agent reads and links; it never writes to a
dashboard, saved query, sheet or ticket.

## Steps

1. Name the exact source: dashboard tile, saved Datadog query, Hex or SQL
   query, or log query. Build a live link with the window baked in:
   `python3 <skill>/scripts/trace_number.py '<logs query>' --from 24h --to now --source '<source name>' --seen '<value the user sees>'`
   (`<skill>` is this skill's folder; `--from` and `--to` take ISO time or 24h, 7d.)
   An unparseable window exits 2 and prints no link. Fix the window; never guess one.
2. Re-run that source for the user's window and filters with the Datadog or
   SQL tool. Fill the printed table: your number, the numerator and the
   denominator, next to the value the user sees, and the delta.
3. Trace one example record from the raw job or row up to the chart. Link each hop.
4. List the 10 most recent rows behind the numerator and the same 10 behind the
   denominator, so the user can audit them.
5. If the claim is someone else's (a comment or memo), give a verdict: right,
   wrong, or right in a narrower scope, and say the scope. Draft a reply only if asked.
6. Report data staleness: the newest record time in the window.

## Rules

- Every source, query, dashboard and sheet named in the answer is a link to the
  live view with the window baked in, not query text alone.
- A delta that is not zero is reported, with the likeliest cause named from the rows.
- If the source cannot be re-run, say which step could not run and why; never fill the table from memory.
