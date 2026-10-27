---
runbook: bugfix
version: 1
applies_to:
  - bugfix
compiled_from:
  - principle-prove-it
  - history-before-reversal
  - why
  - narrow-the-scope
  - repeat-error-stop
  - prove-it-ship-gate
  - split-scope
  - make-pr
playbook-trigger: fix the bug
enforcement_profile: guided
---

# Fixing one reported bug

Work the eight steps below in order. Each heading carries its own binding:
the rule id it compiles from, its level, and the evidence key and harness
event that can see it. The headings are what the router injects.

## 1. Reproduce the failure yourself on the reported surface [principle-prove-it · hard · evidence: failing_run · @Stop]

Drive the real surface until it fires; synthesize the trigger, tighten the
conditions, or add instrumentation if it will not. Paste the failing run.

## 2. Binary-search the cause, reading history before blaming a commit [history-before-reversal · soft]

Form the candidate hypotheses and rule them out with runtime evidence, taking
the split that cuts the most remaining space each pass. Read the history of
any commit before calling it the cause or reverting it.

## 3. Recover why the suspect code is shaped that way [why · soft]

Run the `why` skill over the surviving mechanism before changing it, so a
deliberate guard is not removed as if it were an accident.

## 4. Plan the smallest fix the evidence justifies [narrow-the-scope · soft]

One scoped change, no extras that "might help". When the evidence refutes a
hypothesis, revert what it motivated rather than leaving it in.

## 5. Cut the scope when the same error returns a third time [repeat-error-stop · soft]

Three identical errors with nothing else changed means the attempted scope is
bigger than what has been verified. Say so and take a smaller slice.

## 6. Verify on the original failing surface [prove-it-ship-gate · hard · evidence: pass_line · @Stop]

The original repro now passes, on the same surface, with its output pasted.
Inconclusive or wrong-surface is a failure and gets flagged as one.

## 7. Stage the failing repro before the fix [split-scope · soft]

Commit the failing repro first and the fix on top, so the history reads as
the bug and then its cure. Skip the local test when it would be expensive,
integration-heavy or unclear, and write the reason down.

## 8. Open the pull request through the repo's PR skill [make-pr · soft]

Call `make-pr`, and report what was broken, the cause, the fix, and the
failing-then-passing output verbatim.
