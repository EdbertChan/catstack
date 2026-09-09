---
name: principle-report-the-disqualifier
description: "Apply when writing or gating any report that makes a causal claim or summarises a cumulative outcome — a backtest, an experiment write-up, a capacity or cost model, a postmortem, an eval summary, a benchmark table. The report must carry what would change the reader's decision: what observation would refute the claim, whether the path crossed a state it could not return from, what the headline was before and after the fix, and which unvaried assumption flips the sign."
disable-model-invocation: true
---

# Report the disqualifier

A report is not finished when its numbers are correct. It is finished when a
reader who disagrees with it knows exactly where to look. Every claim has a
disqualifier — one observation that would sink it — and a report that omits
its own disqualifier is persuasive in proportion to how wrong it can be.

Four disqualifiers, four sections. Use the ones that apply.

## 1. What would refute this

Any causal claim states, in the same document, the observation that would
falsify it — a measurement, not a hedge. "This may not generalise" is not a
falsification section; "if the effect survives when X is held constant, the
mechanism is not X, and here is that run" is.

Grade every claim in the report on one visible scale — **measured /
inferred / conjecture** — and put the grade next to the claim, not in a
preamble. A reader must be able to strip the report to its measured rows and
see what is left.

## 2. Did the path survive

A summary statistic computed over a path can describe a path that ended. A
positive year through an account that was liquidated in March; a mean latency
across an interval containing an outage; a mean reward over a trajectory that
terminated; an eventual success after a retry budget was exhausted.

Whenever the process has an **absorbing state** — a barrier it cannot return
from — the report carries a survived yes/no column and the date of absorption,
beside the final value. The expected value across many runs and the outcome of
the one run you get are different quantities, and only the second one is
yours.

## 3. Before and after the fix

When a defect is corrected mid-analysis, report the headline metric under both
readings in the same message, with the sign. A table that quietly contains
both the pre-fix and post-fix cell has published the reversal without saying
it, and the number that travels onward will be whichever one someone quoted
first.

## 4. Which unvaried assumption flips the sign

Every report names its frozen constants — the cost, the threshold, the
window, the rate — and, for each one that appears in the metric expression,
the value at which the conclusion reverses. If no such value exists inside a
plausible range, say so. Disclosure is not this: repeating an assumption
twelve times is not the same as testing it once.

An axis you swept that changed no output row is also a finding. Report it as
inert rather than presenting its cells as distinct results.

## Must never

- Ship a gate that checks a section's *heading* and calls that a content
  check. `grep -qi "falsification"` passes a report that says no
  falsification was attempted. Assert the property, then prove the gate by
  deleting the section body and watching it fail —
  [[principle-assert-invariants-not-last-bug]], step 5.
- Present a headline figure whose cost, fill, or capacity basis is absent.
  Prefix it `PROVISIONAL —` until that basis and its sensitivity range are in
  the same message.
- Let a fan-out end without a terminal aggregation step. A finding stated
  independently in several sibling reports, and read by nobody across them,
  is the most expensive kind of undiscovered result.

## Grounding

- Falsifiability as the demarcation of a real claim → Karl Popper, *The Logic
  of Scientific Discovery* (1959; Ger. 1934).
- Committing to the refuting test *before* seeing the result → Chris Chambers
  and Loukia Tzavella, "The past, present and future of Registered Reports,"
  *Nature Human Behaviour* 6, 29-42 (2022)
  <https://doi.org/10.1038/s41562-021-01193-7>.
- Grading each claim on one visible evidence scale → Gordon H. Guyatt et al.,
  "GRADE: an emerging consensus on rating quality of evidence and strength of
  recommendations," *BMJ* 336, 924-926 (2008)
  <https://doi.org/10.1136/bmj.39489.470347.AD>.
- Why an ensemble average does not describe the single path when the path can
  be absorbed → Ole Peters, "The ergodicity problem in economics," *Nature
  Physics* 15, 1216-1221 (2019) <https://doi.org/10.1038/s41567-019-0732-0>;
  J. L. Kelly Jr., "A New Interpretation of Information Rate," *Bell System
  Technical Journal* 35(4), 917-926 (1956)
  <https://doi.org/10.1002/j.1538-7305.1956.tb03809.x>.
- Reporting the whole space of defensible specifications rather than one →
  Uri Simonsohn, Joseph P. Simmons, Leif D. Nelson, "Specification curve
  analysis," *Nature Human Behaviour* 4, 1208-1214 (2020)
  <https://doi.org/10.1038/s41562-020-0912-z>; Andrea Saltelli et al., "Why so
  many published sensitivity analyses are false," *Environmental Modelling &
  Software* 114, 29-39 (2019)
  <https://doi.org/10.1016/j.envsoft.2019.01.012>.
- Findings that exist only across sibling reports and are never aggregated →
  Robert Rosenthal, "The file drawer problem and tolerance for null results,"
  *Psychological Bulletin* 86(3), 638-641 (1979)
  <https://doi.org/10.1037/0033-2909.86.3.638>.
- The "no losing day" / too-good smell test lives in [[principle-no-lookahead]],
  not here — this skill is about what a report must disclose, that one is
  about what an evaluation may read.
