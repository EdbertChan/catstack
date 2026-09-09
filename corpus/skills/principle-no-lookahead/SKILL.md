---
name: principle-no-lookahead
description: "Apply to any evaluation, backtest, benchmark, grader, or training run over data with a time axis or an ordered decision sequence. Score a decision only against inputs that existed before that decision was made. Covers what the field calls look-ahead bias, target leakage, point-in-time correctness, and repainting. Reach for it on: a backtest or walk-forward run, a feature computed over a full history, a retrieval or agent eval, a label assigned after the outcome was known, or any result that looks too good."
disable-model-invocation: true
---

# No lookahead

A result is a result only if the decision behind it could have been made at
the moment it is credited to. Otherwise it is a measurement of hindsight.

The failure has a formal name: **leakage** — "the introduction of information
about the target of a data mining problem which should not be legitimately
available to mine from" (Kaufman et al., see Grounding). In time-series work
it is **look-ahead bias**; the correctness property it violates is
**point-in-time correctness**; the technical-analysis artifact that causes it
is a **repainting** indicator. One defect, four vocabularies.

## The shape

Two artifacts get confused because they are rendered from the same data:

| | Display artifact | Decision artifact |
|---|---|---|
| Answers | what happened | what would I have done |
| May read | the whole history | only rows at or before `t` |
| Revised later | legitimately, yes | never |

A chart, a labelled dataset, an annotated log, a resolved ticket, and a
post-hoc report are all display artifacts. They are drawn *after*, and are
allowed to move a marker back onto the moment the thing "really" happened.
Feed one into a decision evaluation and the decision is credited with
knowledge it did not have.

**The leaked value can be entirely real and the leak still total.** The leak
is in *when the decision became available*, not in the number's accuracy.
A price, a label, or a document can be genuine at time `t` while the
instruction to act on it does not exist until `t + k`.

## Must always

- **Name the cutoff before the first measurement.** For every input, record
  two timestamps: what it is *about*, and when it became *knowable*. Only
  the second one may gate a decision. If a source cannot tell you the
  second, it is a display artifact until proven otherwise.
- **Run the truncation test.** Recompute the decision from only the data
  available at time `t`, and compare it to what the full-history computation
  says at that same `t`. Any disagreement at any `t` is a leak, and the
  disagreeing indices name it. Ten cut points expose a gross leak in
  seconds; a replay at every step is the proof.
- **Separate knowability from actionability.** The truncation test proves the
  input existed at `t`. It does not prove the action was executable at `t`.
  Name the execution cutoff too: the earliest moment the decision could have
  reached the world, and the price, latency, or capacity it would have met
  there. A decision that observes a bar's close and fills at that same close
  is zero-latency, and zero latency is a form of hindsight the prefix test
  cannot see.
- **Bind the test to the artifact that produced the number**, not to a
  library function beside it. A causality test that guards `compute()`
  proves nothing about a script that imports `compute()` and passes it a
  different mode. The gate belongs on the path the reported number came out
  of — including throwaway analysis scripts, notebooks, and heredocs.
- **Treat an implausibly good result as a bug report, not an achievement.**
  Fix the implausibility ceiling from the domain's own known best *before*
  running, and stop on any of: a score above what the best known
  practitioner achieves; an error near zero; a monotone result with no bad
  period across a span long enough to contain one; a metric that improves
  when an input that should be irrelevant is added; a parameter sweep where
  every cell wins. The stronger the number, the earlier you stop. Stop and
  find the mechanism — leakage, an inert axis that never varied the output, a
  frozen constant, or a coding error — before reporting the number at all.
  Report the number of configurations tried alongside the best one; without
  it, a reader cannot tell skill from selection.
- **Re-run the cutoff check after any change to what an input reads** — a
  new normalization, a rolling window, a resample, a join, a smoothing term,
  a re-label. Each can silently widen the window a value is computed over.
- **Reject a negative offset.** Any shift, lag, or window parameter exposed
  to a caller must refuse values that reach forward. An unvalidated
  `shift(k)` is a lookahead switch with no label on it.

## Must never

- Score a decision against a label that was assigned with knowledge of the
  outcome.
- Accept "it only reads past data" from a grep, a variable name, a
  docstring, or a commit message. Causality is a property of the output,
  measured. It is not a property of the source, read.
- Let a display mode and a decision mode share a return type. If one
  function can emit both, a caller will eventually pass the wrong one and
  nothing will say so. Make the display result structurally unable to reach
  the scoring path.
- Report a result whose sign depends on an assumption that was never varied.
  If one unswept constant flips the conclusion, that constant is the finding.
- Publish a number produced before the truncation test ran. On discovery,
  void the old numbers **in place** — move them to a `voided/` path and
  retract the headline — rather than deleting them, so the record shows what
  was believed and for how long.

## The cheap test, in general form

## Grounding

- Leakage, formalized, with the legitimacy-in-time condition and the
  learn-predict separation that avoids it → Shachar Kaufman, Saharon Rosset,
  Claudia Perlich, Ori Stitelman, "Leakage in Data Mining: Formulation,
  Detection, and Avoidance," *ACM TKDD* 6(4), Article 15 (2012)
  <https://doi.org/10.1145/2382577.2382579>. This is the paper that names
  this exact failure; its KDD-Cup and INFORMS case studies are both
  "implausibly good result turned out to be a leak."
- Evaluating only from an origin that moves forward through the data →
  Leonard J. Tashman, "Out-of-sample tests of forecasting accuracy: an
  analysis and review," *International Journal of Forecasting* 16(4),
  437-450 (2000) <https://doi.org/10.1016/S0169-2070(00)00065-0>. Rolling
  origin is the truncation test as a standard evaluation design.
- Why a too-good backtest is evidence about the search process rather than
  the strategy, and why the count of configurations tried must be reported →
  David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu,
  "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest
  Overfitting on Out-of-Sample Performance," *Notices of the AMS* 61(5),
  458-471 (2014) <https://www.ams.org/notices/201405/rnoti-p458.pdf>.
- Purged cross-validation and embargo, for label overlap leaking across a
  split → Marcos López de Prado, *Advances in Financial Machine Learning*,
  Wiley (2018), ch. 7 and ch. 11.
- "Repainting," for a display artifact that moves a marker backward:
  **no known peer-reviewed prior art.** It is vendor and forum vocabulary
  only. Cite the mechanism, not the word.

Related: [[principle-assert-invariants-not-last-bug]] (the truncation test is
the class invariant, not a patch for the leak you found);
[[principle-explicit-errors]] (a suppressed or unvalidated offset is how the
leak gets in silently); [[principle-report-the-disqualifier]] (what the
report must disclose once the evaluation is clean).
