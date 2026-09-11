---
name: principle-explicit-errors
description: "Apply whenever code handles an exception (catch, suppress, translate, retry), decides to skip, drop, truncate, or stop early on data (an empty parse, a missing lookup, an unpriced row, a lookback or coverage cap, a loop that reads only the first source), or writes the text of an error, failure, or rejection message that a person or agent will read to fix the problem."
disable-model-invocation: true
---

# Make errors and failures explicit

Every failure path must make its disposition visible: fail fast, propagate,
translate into a named domain result, or suppress only a narrow, documented
case whose absence is safe and observable when that assumption changes.
Each rule below restates standard practice (see Grounding).

## Exceptions

An empty or comments-only handler is not an error policy. It hides failures
from callers, logs, tests, and maintainers. Do not write `catch {}`,
`except: pass`, ignored promise rejections, or equivalent silent fallbacks.
Replace them with an explicit action and keep the original error context.

Mechanical enforcement: `engine/hooks/explicit-failures` (advisory PreToolUse hook, on by default; its README lists the shapes it catches).

Before adding an exception path, answer in code or its nearby test: which
errors are expected, what happens to each, and how would an unexpected error
become visible? Catch specific exceptions, not a whole operation, and prefer
a lint rule or structural check when the policy can be machine-enforced.

## Error messages name their cause

A failure message is read by whoever fixes it next, often an agent with no
other context. Write it so that reader can act without re-running anything
or re-deriving what the code saw:

- **Label the failure.** Open with a stable kind the reader can search for
  (`review-unit-conflict`, `E_TIMEOUT`, `unparsed`), not a bare "error" or
  "failed".
- **Name the cause and the input that caused it.** Quote the offending
  value, the matched words, the path, the limit that was hit. "mentions
  multiple review units (validation-policy, write-path)" is a verdict;
  adding "Matched words: validation-policy [retry]; write-path [submit]" is
  the cause, and it shows at once when the match was wrong (a file name
  counted as a word).
- **Say what was expected and what was found.** `expected 200, got 401`,
  not `request failed`.
- **Keep the original error.** Chain it (`raise ... from err`,
  `new Error(msg, { cause })`); a summary never replaces it.
- **Point at the fix when one is known**: the flag, the command, the section
  to change, in one line.
- **A check that could not run says so.** "could not check: <reason>" is its
  own message, never the text of a pass or a fail.

A checker whose message names the rule but not the input that tripped it
forces every reader to reverse-engineer the match, and the reverse
engineering is where wrong fixes come from.

## Dropped rows, truncated ranges, early exits (completeness)

A bare `continue`, early `return`, or `break` on a failed lookup, an empty
parse, or a coverage cap is the same defect as `except: pass`: the failure
happened and nothing says so. Every such path gets one of three actions —
raise, log with enough context to find the row, or emit the row with a
status column (`unknown`, `not_disclosed`, `unparsed`, `unpriced`,
`unmatched`, `truncated`, …) and a one-line reason. A fabricated value and
an absent row are both wrong; the status row is the only allowed third way.

- "Empty parse ⇒ drop the row" is a banned rule shape. The allowed shape is
  "empty parse ⇒ emit the row with `status=unparsed` and the reason."
- A loop that stops at the first source, filing, or page must reconcile
  against a control total: rows emitted equals rows the source index says
  exist. "The grid ended" is not evidence the source ended.
- A cap that cuts data says so in the output (`truncated`, with the cap), the
  way a paginated API returns an explicit truncated flag — not only in a
  comment or a log line.
- The status column is data, not a comment: queryable, graded, and handled
  explicitly downstream. A status row a later step quietly filters out has
  moved the drop, not fixed it.
- Graders and tests measure completeness (recall), not only accuracy
  (precision). Every expected row — every source-disclosed period, ledger
  event, entity — is present, or present as a status-marked row. "Every
  emitted value traces to a source" cannot see a row that was never emitted.

## Grounding

The repo context is a batch data pipeline (filings in, CSV grids out), not a
long-running service; each line says how the source fits that.

- Silent handlers → Tim Peters, PEP 20 "The Zen of Python" (2004): "Errors
  should never pass silently. Unless explicitly silenced."
  <https://peps.python.org/pep-0020/>; Joshua Bloch, *Effective Java* 3rd ed.
  (2018), Item 77 "Don't ignore exceptions". A batch job that swallows an
  error ships a wrong CSV under a green run, so this applies as written.
- Fail immediately and visibly → Jim Shore, "Fail Fast", *IEEE Software*
  21(5) (2004) <https://martinfowler.com/ieeeSoftware/failFast.pdf>. Shore's
  "return a default value and everything will seem fine" is the dropped-row
  case exactly.
- Catch specific exceptions → PEP 8 <https://peps.python.org/pep-0008/>,
  lint code E722; machine-enforceable here, so prefer the lint over prose.
- Status row, not a dropped row → Ralph Kimball, "Design Tip #164: Have You
  Built Your Audit Dimension Yet?" (2014)
  <https://www.kimballgroup.com/2014/03/design-tip-164-built-your-audit-dimension/>:
  per-row data-quality flags (missing, estimated, unlikely) are columns.
  Same shape as Rust `Result` and Rob Pike, "Errors are values" (2015)
  <https://go.dev/blog/errors-are-values>: the failure is a value the next
  step must handle. Explicit truncation is the paginated-API convention
  (S3 `ListObjectsV2` returns `IsTruncated`).
- Control totals and record-count reconciliation → standard batch-interface
  reconciliation (SOX/ITGC); Google SRE Workbook ch. 13, "Data Processing
  Pipelines" (2018) <https://sre.google/workbook/data-processing/> defines
  completeness and correctness SLOs. The expected count for the history
  grid and parsers comes from the filing index.
- Count omissions, not only fabrications → precision vs. recall, C. J. van
  Rijsbergen, *Information Retrieval* (1979); DAMA-DMBOK data-quality
  dimension "completeness". A precision-only grader cannot see recall.
- Error messages name their cause → Google Developers, "Writing helpful
  error messages", *Technical Writing* course
  <https://developers.google.com/tech-writing/error-messages>: identify the
  cause, identify the invalid input, explain how to fix it. Evan Czaplicki,
  "Compiler Errors for Humans" (2015)
  <https://elm-lang.org/news/compiler-errors-for-humans>: show the exact
  code that failed and what was expected. Keeping the original error is
  exception chaining, PEP 3134 <https://peps.python.org/pep-3134/> and
  ECMAScript 2022 `Error` `cause`.
- Contrast: Erlang "let it crash" (Joe Armstrong, PhD thesis, 2003) fits at
  the job level — a Dagster asset should fail loudly rather than emit a
  partial grid — but not per row: a batch re-run on the same input crashes
  the same way, so per-row policy has to be raise / log / status row.

Practices this repo could adopt next (reconciliation, mutation testing of
the gates, property-based tests, data expectations) are in
[references/related-practice.md](references/related-practice.md). This
principle complements [[principle-encode-lessons-in-structure]] and
[[principle-assert-invariants-not-last-bug]] (assert the class, not the
instance).
