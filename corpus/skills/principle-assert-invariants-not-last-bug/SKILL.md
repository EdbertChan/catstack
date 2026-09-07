---
name: principle-assert-invariants-not-last-bug
description: "Apply after a bug ships past review or a passing grade/check: assert the general class of failure instead of patching only the specific instance that was caught. Use on /reflect, whenever a fix's own commit message reads like 'fix X for ticker/case Y', or whenever a fix makes a row disappear instead of shipping it with a status."
disable-model-invocation: true
---

# Assert invariants, not the last bug name

Generalized from a real repo's incident log: the same shape of bug (an
identity/provenance/uniqueness invariant) shipped four separate times
because each fix patched the specific case a judge or reviewer had just
pointed at, not the general rule — so the next differently-shaped instance
of the same class sailed through untouched.

The same log later showed the mirror-image blind spot: every check asked
"did we invent a value?" and none asked "did we drop a row?" — so a batch
of defects that were all *missing* rows passed every grade.

## Why this exists

Patching "the AUR case" doesn't stop a structurally identical bug from
shipping as "the SERV case" next week. Each time a fix targets only the
instance that was caught, the *rule* that would have caught every other
instance never gets written down or enforced — so the class stays real, and
grading/review stays blind to every case except the one already fixed.

A rule also has a shape, and a one-sided rule is a half-written invariant.
"Never invent" without "never silently omit" tells the code the safest
thing to do with a hard row is to skip it — which is exactly how a sell
with no matching cost lot, a table that parsed to zero rows, or a period
grid that stopped at the first source all shipped clean.

## The method

1. **Name the invariant in one line.** Not "AUR shouldn't duplicate" —
   "every (period, entity) pair has exactly one row."
2. **Name its omission twin in the next line.** For every "must not
   invent / must not fabricate / must not duplicate" rule, write the paired
   "must not be missing" rule: "every period the source discloses and every
   event the ledger records appears in the output, as a value or as a
   status-marked row." A no-invent rule with no no-drop twin is not done.
3. **Encode both in code** — an assert, a coalesce, a refuse-to-ship check,
   a completeness count — for entities/cases you haven't seen yet, not just
   the one that broke.
4. **Encode both in the relevant skill/doc**, in assert language ("X must
   always Y"), not as "remember the AUR incident."
5. **Re-validate** (re-run the grading/review/test suite) before claiming
   fixed — a fix isn't proven until the same class of check runs clean
   again, not just the one case that originally failed.

**Steps 3 and 4 land together, in the same change.** A principle documented
without a matching code change is invisible drift: the doc says the rule
exists, nothing enforces it, and only a later validation run (if one ever
exercises that exact path) reveals the gap. Never add an invariant to a
skill/doc as a "the code should eventually do this" placeholder — either fix
the code in the same change, or don't document the rule yet.

## Never invent, never silently omit

An unparseable, unpriced, uncovered, or unmatched row still ships. It
carries an explicit status column (`unknown`, `not_disclosed`, `unpriced`,
`unmatched`, `truncated`, …) and a one-line reason — not a fabricated value,
and not an absent row.

- "Empty parse ⇒ drop the row" is a banned rule shape. The allowed shape is
  "empty parse ⇒ emit the row with `status=unparsed` and the reason."
- A silent `continue`, early `return`, or `break` on a missing lookup is the
  omission form of an escape hatch. It must be named in the skill, and it
  must emit a status row rather than nothing.
- A loop that stops at the first source, the first filing, or the first
  page must prove it reached the last one; "the grid ended" is not evidence
  that the source ended.
- Grading must count omissions as well as fabrications. Every
  source-disclosed period and every ledger event (every sell, every filing,
  every entity) must appear in the output, or appear as a status-marked row
  with a reason. A grader that only asks "is each emitted value real?"
  cannot see a row that was never emitted; it also has to ask "is every
  expected row present?"
- The status column is data, not a comment. It is queryable, it is graded,
  and downstream consumers must handle it explicitly — a status row that a
  later step quietly filters out has just moved the drop, not fixed it.

## Anti-patterns

- "We checked the one case that broke" (should be every case of that shape).
- "It looks fine now" (checked the surface, not the invariant).
- "Every emitted value traces to a source, so the output is correct" (a
  fabrication check with no completeness check — the missing rows are
  invisible to it).
- "The parser returned zero rows, so there was nothing to emit" (zero rows
  from a source known to disclose data is an `unparsed` status row per
  expected period, not an empty table).
- "No matching prior record, so skip it" (a `continue` that deletes an
  event from the ledger; ship it as `unmatched` with the reason).
- "The rubric/reviewer allowed this shortcut" (a shortcut that passes review
  by accident is still the escape hatch that will break the next case).
- "Every X does Y" as a blanket rule when the real rule has an exception
  class — restating the common case as universal is itself the bug (a
  15-instance form-in-instance example: "every exit forces the value to
  zero" was true for exits with a real filed value behind them, and false
  for identity-only exits that never had one — the blanket version invented
  a fabricated number for the second case).
- Adding a code path "for continuity" without naming it in the skill and
  either banning it or tightly typing it — an untracked escape hatch that
  happens to look rubric-compliant is how the same class recurs.

## No silent escape hatches

If a code path exists "just for continuity" or "just to keep things
looking consistent," it must be named explicitly in the relevant skill
**and** either banned outright or tightly typed. An untracked shortcut that
happens to pass today's checks is exactly the shape that lets the same class
of bug recur under a new name.

The same applies to code paths that exist "just to skip the hard rows."
Skipping is a decision about the output; it has to be visible in the
output as a status row, never only in the control flow.
