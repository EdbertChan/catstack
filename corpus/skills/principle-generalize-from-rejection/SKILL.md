---
name: principle-generalize-from-rejection
description: "Apply when a mechanical gate — a lint, validator, blocked-command guard, or CI check — rejects your output for the same reason twice in one session. Fix the generation pattern producing the violation, not just the specific instance."
disable-model-invocation: true
---

# Generalize from Rejection

When a repo-specific gate rejects you, the lesson is the rule it's enforcing, not the one output that tripped it. Fix the pattern that's generating violations, so the next output doesn't need the same correction.

**Why:** A rejection with an explanation is free information — the gate already told you what's wrong and often why. Treating each rejection as an isolated retry (change one thing, resubmit, hope) burns turns and tokens re-discovering the same rule against new inputs, when the fix generalizes across all of them.

**Pattern:**
- On the first rejection, read the full message, not just the pass/fail. Most validators explain the rule, not just that it failed.
- Before retrying, ask: does this fix apply only to the thing you just submitted, or to how you've been generating this class of output? If the latter, fix the generation step, not just this instance.
- If the same class of rejection fires a second time in the same session, stop and generalize explicitly — don't submit a third variation before checking whether the underlying pattern is still present elsewhere in what you're about to submit.
- Escalating a fix's *parameters* (a longer timeout, a different retry count) without changing *what's actually being checked* is not generalizing — it's the same mistake with a bigger dial.

**Battle-tested:** a corpus retrospective found this three separate ways in one pass. A PR-body/review-unit validator rejected the same "one review unit per PR" violation 8 times outright plus 33 warnings, across at least 4 different branches in one session — the agent kept drafting multi-unit PR bodies instead of internalizing the rule after the first rejection. A blocked-command guard (long-running `sleep` calls) fired on the identical command three separate times at different points in the same session. And a disk-usage probe over SSH was retried five times with an escalating timeout (30s → 60s → 45s → 90s → 100s) before the agent finally diagnosed the real cause — degraded disk I/O — instead of continuing to guess at a bigger number.
