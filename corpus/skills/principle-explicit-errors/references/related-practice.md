# Related practice: other things we could do and how they fit

Read this when the two principles ([../SKILL.md](../SKILL.md),
[[principle-assert-invariants-not-last-bug]]) are already applied and the
question is "what else does the field do about silent drops and
instance-only fixes?" Each entry: what it is, the source, where it would
plug into hidden_stock's holdings pipeline (history grid, parsers,
realized/Dietz, grading board, judges), and a one-line cost/benefit. The
user asked specifically for tests that prove a gate works, so the first two
are evaluated in more depth.

## 1. Record-count reconciliation (control totals)

What: before shipping, compare rows emitted against an independent expected
count — filings in the EDGAR index vs. periods in the grid, table rows found
by the parser vs. rows written, ledger events vs. realized lots. A mismatch
ships as a named status or fails the run; it never ships silently.

Source: standard batch-interface control (SOX/ITGC reconciliation); Google
SRE Workbook ch. 13 "Data Processing Pipelines" (2018), completeness SLO
<https://sre.google/workbook/data-processing/>; Kimball & Caserta, *The Data
Warehouse ETL Toolkit* (2004), audit dimension and error event schema.

Plug-in: `hidden_stock/quirks/holdings/history.py` (`build_holdings_history`
already collects the 13F period list — that list is the control total for
the grid); `parse_notes.py` / `parse_13f.py` (tables seen vs. rows emitted);
`reconcile.py` is the natural home for the cross-source comparison.

Cost/benefit: cheap (one count per stage, assert equality or emit
`truncated`); catches the entire "loop stopped early" class the seven-defect
review found, independent of which ticker triggered it. Adopt first.

## 2. Mutation testing of the gates

What: deliberately reintroduce each defect class (delete the status row,
restore the bare `continue`, drop a period) and require the gate to fire; a
gate that stays green under its own defect is dead code. Mutation score =
killed mutants / total mutants.

Source: DeMillo, Lipton, Sayward, "Hints on Test Data Selection", *IEEE
Computer* 11(4) (1978); tools: PIT <https://pitest.org/> (JVM), `mutmut`
and `cosmic-ray` (Python).

Plug-in: the grade precheck and `validate.py` assertions, plus the board
script (`grade_holdings_sheet.py`). hidden_stock already has a hand-rolled
version of this shape on its gate-effectiveness branch: one `Defect` per
original bug, each a single mutation of a clean synthetic parent, asserting
both `fires` and `silent` through the real pipeline path. The generic tool
(`mutmut run --paths-to-mutate hidden_stock/quirks/holdings/validate.py`)
adds the mutants nobody thought to hand-write.

Cost/benefit: the hand-rolled fixture pair is the right first step and is
what proves "the fix and the gate" (principle step 5); full `mutmut` over
the pipeline is slow (each mutant re-runs the suite) and noisy on parsers,
so run it only over `validate.py` / precheck code, in CI on a schedule, not
per PR.

## 3. Property-based tests for the invariants

What: state the invariant as a predicate and let the framework generate
inputs — random ledgers, random period grids — and shrink any
counterexample to the smallest failing case.

Source: Claessen and Hughes, "QuickCheck", *ICFP* (2000)
<https://dl.acm.org/doi/10.1145/351240.351266>; `hypothesis` for Python.

Plug-in: `performance.py` (realized P&L and Dietz): with zero external flows
the Dietz return equals the price return; realized + unrealized + cash flows
conserve; every sell matches a lot or emits `unmatched`. `identity.py`:
every (period, entity) key is unique for any generated grid.

Cost/benefit: moderate to write generators; pays back on exactly the
"case we haven't seen yet" the principle names, and is the only listed
practice that finds a new instance before a judge does.

## 4. Data expectations at the table level

What: declarative checks on the emitted CSVs — not-null, unique key,
row-count-between, accepted values for the status column, referential
integrity from grid rows to filing URLs — run as a suite after export.

Source: Great Expectations
<https://greatexpectations.io/legacy/v1/expectations/expect_table_row_count_to_be_between/>;
Schelter et al., "Automating Large-Scale Data Quality Verification", *VLDB*
11(12) (2018) (Deequ); dbt `unique` / `not_null` / `relationships` tests.

Plug-in: after `export.py` writes CSVs, before the board reads them; the
`HISTORY_COLUMNS` / `HOLDINGS_COLUMNS` schemas become the expectation suite.

Cost/benefit: cheap and readable; overlaps with `validate.py`, so adopt as
a rewrite of that file into a declarative suite rather than a second layer.

## 5. Golden-data correctness checks

What: inject inputs with a known correct output (a synthetic parent with a
hand-built filing set) and compare emitted vs. expected end to end.

Source: Google SRE Workbook ch. 13, correctness SLO via "golden data"
<https://sre.google/workbook/data-processing/>.

Plug-in: the TESTCO synthetic parent on the gate-effectiveness branch is
already this; extend it with one filing per known parser quirk (off-grid
column, HK annual, 13D/G event date).

Cost/benefit: fixture upkeep per quirk; the only practice that proves the
pipeline output, not just its gates.

## 6. Characterization tests on the parsers

What: freeze the current output of each parser for each real filing
fixture; any change to the output fails until a human accepts the new
snapshot.

Source: Michael Feathers, *Working Effectively with Legacy Code* (2004),
"characterization tests".

Plug-in: `parse_notes.py`, `parse_hk_annual.py`, `parse_13f.py` over the
existing fixture filings.

Cost/benefit: very cheap; catches drops introduced by refactors, but says
nothing about whether the frozen output was right — pair with 1 or 5.

## 7. Audit column / error event table

What: every emitted row carries provenance and quality flags (source URL,
parser version, `status`, reason); rows that failed are written to an error
event table instead of vanishing.

Source: Kimball, "Design Tip #164: Have You Built Your Audit Dimension
Yet?" (2014)
<https://www.kimballgroup.com/2014/03/design-tip-164-built-your-audit-dimension/>.

Plug-in: the status column already exists in the principle; the error event
table is the missing half — `export.py` writes `<ticker>_errors.csv` and the
board reads it as a required input.

Cost/benefit: one extra CSV; makes "count omissions" a query instead of a
review pass.

## 8. Errors as values in parser signatures

What: parsers return a sum type (`Parsed | Unparsed(reason)`) rather than
raising or returning an empty list; callers must handle both arms.

Source: Rob Pike, "Errors are values" (2015)
<https://go.dev/blog/errors-are-values>; Rust `Result` and `#[must_use]`;
Alexis King, "Parse, don't validate" (2019).

Plug-in: `parse_notes.parse_investment_notes` and `sec_13g` collectors;
`history.py` then cannot forget the `Unparsed` arm because the type checker
sees the match.

Cost/benefit: a signature change across a few modules; removes the
"empty list looks like success" ambiguity structurally (fix hierarchy
tier 1).

## 9. Defect classification in the judge digest

What: tag every board finding with an orthogonal defect class (omission vs.
fabrication vs. identity vs. arithmetic) and trend the counts.

Source: Chillarege et al., "Orthogonal Defect Classification", *IEEE TSE*
18(11) (1992); Google SRE, "Postmortem Culture" (2016).

Plug-in: `judge_digest.py` already aggregates judge output; add the class
field to the grade schema and count per class per run.

Cost/benefit: nearly free; turns "the same class shipped four times" from a
memory into a number the next reflect pass can read.

## 10. Fail fast at the job boundary

What: a Dagster asset fails when a completeness ratio drops below threshold
instead of materializing a partial grid.

Source: Jim Shore, "Fail Fast", *IEEE Software* 21(5) (2004); Erlang "let
it crash" at the supervisor level (Armstrong, 2003).

Plug-in: `hidden_stock/jobs.py` asset boundary, using the counts from 1.

Cost/benefit: one check; trades a partial-but-green run for a red run with
a named cause, which is what every grader downstream wants.

## What the field does not do

Nothing in the literature supports "document the rule and fix the code in
the same commit" as a general rule; that is repo-local (enforced by
`scripts/check_codify_has_code.py`) and stays because prose is the weakest
fix tier here. Likewise the specific status vocabulary (`unpriced`,
`not_disclosed`) is this repo's; the field's term is a data-quality flag or
error event, and any vocabulary is fine as long as it is a column.
