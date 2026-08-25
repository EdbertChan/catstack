---
name: principle-assert-invariants-not-last-bug
description: "Apply after a bug ships past review or a passing grade/check: assert the general class of failure instead of patching only the specific instance that was caught. Use on /reflect, or whenever a fix's own commit message reads like 'fix X for ticker/case Y.'"
disable-model-invocation: true
---

# Assert invariants, not the last bug name

Generalized from a real repo's incident log: the same shape of bug (an
identity/provenance/uniqueness invariant) shipped four separate times
because each fix patched the specific case a judge or reviewer had just
pointed at, not the general rule — so the next differently-shaped instance
of the same class sailed through untouched.

## Why this exists

Patching "the AUR case" doesn't stop a structurally identical bug from
shipping as "the SERV case" next week. Each time a fix targets only the
instance that was caught, the *rule* that would have caught every other
instance never gets written down or enforced — so the class stays real, and
grading/review stays blind to every case except the one already fixed.

## The method

1. **Name the invariant in one line.** Not "AUR shouldn't duplicate" —
   "every (period, entity) pair has exactly one row."
2. **Encode it in code** — an assert, a coalesce, a refuse-to-ship check —
   for entities/cases you haven't seen yet, not just the one that broke.
3. **Encode it in the relevant skill/doc**, in assert language ("X must
   always Y"), not as "remember the AUR incident."
4. **Re-validate** (re-run the grading/review/test suite) before claiming
   fixed — a fix isn't proven until the same class of check runs clean
   again, not just the one case that originally failed.

**Steps 2 and 3 land together, in the same change.** A principle documented
without a matching code change is invisible drift: the doc says the rule
exists, nothing enforces it, and only a later validation run (if one ever
exercises that exact path) reveals the gap. Never add an invariant to a
skill/doc as a "the code should eventually do this" placeholder — either fix
the code in the same change, or don't document the rule yet.

## Anti-patterns

- "We checked the one case that broke" (should be every case of that shape).
- "It looks fine now" (checked the surface, not the invariant).
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
