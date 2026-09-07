---
name: principle-explicit-errors
description: "Apply whenever code handles an exception (catch, suppress, translate, retry) or decides to skip, drop, truncate, or stop early on data: an empty parse, a missing lookup, an unpriced row, a lookback or coverage cap, a loop that reads only the first source."
disable-model-invocation: true
---

# Make errors and failures explicit

Every failure path must make its disposition visible. That holds for an
exception and for a row the code cannot fill: handle it, propagate it,
translate it into a named domain result, or suppress only a narrow,
documented case whose absence is safe and observable when that assumption
changes.

## Exceptions

An empty or comments-only exception handler is not an error policy. It hides
failures from callers, logs, tests, and future maintainers. Do not write
`catch {}`, `except: pass`, ignored promise rejections, or equivalent silent
fallbacks. Replace them with an explicit action and preserve the original
error context where the failure may matter.

Mechanical enforcement: `engine/hooks/explicit-failures` (advisory PreToolUse hook, off by default; its README lists the shapes it catches).

Before adding an exception path, answer three questions in code or its nearby
test: which errors are expected, what happens to each one, and how would an
unexpected error become visible? Prefer a narrow predicate over catching a
whole operation, and prefer a structural check or lint rule when the policy
can be machine-enforced.

## Dropped rows, truncated ranges, early exits

A bare `continue`, early `return`, or `break` on a failed lookup, an empty
parse, or a coverage cap is the same defect as `except: pass`: the failure
happened and nothing says so. Every such path gets one of three actions —
raise, log with enough context to find the row, or emit the row with a
status column (`unknown`, `not_disclosed`, `unparsed`, `unpriced`,
`unmatched`, `truncated`, …) and a one-line reason. A fabricated value and
an absent row are both wrong; the status row is the only allowed third way.

- "Empty parse ⇒ drop the row" is a banned rule shape. The allowed shape is
  "empty parse ⇒ emit the row with `status=unparsed` and the reason."
- A loop that stops at the first source, filing, or page must prove it
  reached the last one. "The grid ended" is not evidence the source ended.
- A lookback or coverage cap that cuts data says so in the output
  (`truncated`, with the cap), not only in a comment or a log line.
- The status column is data, not a comment: queryable, graded, and handled
  explicitly downstream. A status row that a later step quietly filters out
  has moved the drop, not fixed it.
- Graders and tests count omissions, not only fabrications. Every expected
  row (every source-disclosed period, every ledger event, every entity) is
  present, or present as a status-marked row. "Every emitted value traces to
  a source" cannot see a row that was never emitted.

One incident set this shape: seven defects found in a single review pass of
the hidden_stock holdings pipeline were all missing rows — a sell with no
cost lot that hit `continue`, tables that parsed to zero rows, a period grid
that stopped at the first source — and every one passed every never-invent
check.

This principle complements [[principle-encode-lessons-in-structure]]: repeated
error-handling corrections belong in a checker, type, or runtime invariant,
not in another reminder to be careful. Once a failure path is explicit,
[[principle-assert-invariants-not-last-bug]] covers the other half: assert
the class, not the instance.
