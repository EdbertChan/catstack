---
name: thrash-reflect-automate
description: >-
  On a grading/validation board FAIL or NEEDS_WORK, or the user saying
  "/thrash": auto-run a short reflect, fix the class of bug (not just the
  named instance), codify the invariant in the relevant skill/rule, then
  automate a catch and re-validate. Collapse phrase for "reflect and
  automate after every failure" — do not wait for the user to re-prompt.
---

# Thrash → reflect + automate (no re-prompt)

Generalized from a real repo's hand-built QA loop (a swarm-grading pipeline
with independent judges + a mechanical precheck): the specifics below assume
some repo-owned grading/validation script and a repo-owned principle-doc
skill exist already. Adapt the trigger and the "codify" target to whatever
this repo actually has — the discipline (no re-prompt, fix the class, land
code and doc together) transfers regardless.

When a grading/validation board comes back FAIL / NEEDS_WORK, the user
says **`/thrash`**, or `token_audit.py` flags `intervention-must-automate`
(same-type complaint, forced restatement, "you fucked up/messed up" aimed
at the agent), do **not** wait for a long "after every failure reflect
and automate" phrase — run the sequence below immediately. User
involvement of that class is FAIL, same as a board FAIL.

## Auto sequence (every FAIL turn)

1. **Reflect** (short): why it shipped, the class of bug, why it was missed.
2. **Fix the class**, not just the named instance — the ticker, the file,
   the one input that happened to trigger it. If this repo has a companion
   "assert invariants, not the last bug" skill, prefer it here.
3. **Codify the invariant** in the relevant skill/rule/doc, in assert
   language ("X must always Y") — not "remember when Z broke."
4. **Automate a catch**: one concrete mechanical check that would catch this
   next time (a CI gate, a mechanical precheck in the grading script, a new
   regression test). Prefer whatever the failing board's own
   recommended-fix/root-cause field already suggests.
5. **Re-validate** if that was the active loop — do not claim fixed without
   a new passing board/run.

## Do not

- Skip reflect on FAIL because a mechanical/automated check happened to pass.
- Ask "should I reflect?" — just do it.
- Commit or open any auto-generated automation editor unless the user asks.
- Paraphrase away a FAIL on the judgment board.
- Land step 3 (codify in the skill) without step 2 (the matching code fix) —
  a documented invariant with no code enforcing it is invisible drift until
  the next validation run happens to catch it. See
  `principle-assert-invariants-not-last-bug`.
