---
name: principle-assert-invariants-not-last-bug
description: "Apply after a bug ships past review or a passing grade/check: assert the general class of failure instead of patching only the specific instance that was caught. Use on /reflect, whenever a fix's own commit message reads like 'fix X for ticker/case Y', or whenever a fix makes a row disappear instead of shipping it with a status."
disable-model-invocation: true
---

# Assert invariants, not the last bug name

After a bug ships past review or a passing check, encode the class of
failure as an invariant, not a fix for the instance that was caught.
Patching "the AUR case" does not stop a structurally identical bug from
shipping as "the SERV case": the rule that would catch every instance is
never written down or enforced, so review stays blind to every case except
the one already fixed. Under its usual names — invariant, contract,
property, regression test — this is standard practice (see Grounding).

## The method

1. **Name the invariant in one line**, as a predicate that holds in every
   state. Not "AUR shouldn't duplicate" — "every (period, entity) pair has
   exactly one row."
2. **Name its completeness twin in the next line.** Every "must not invent"
   (precision) rule gets a "must not be missing" (recall) rule; how a hard
   row ships is [[principle-explicit-errors]].
3. **Encode both in code** — an assertion, a uniqueness or not-null
   expectation, a refuse-to-ship check, a record-count reconciliation — over
   every case of that shape, not the one that broke. A property-based test
   generates the cases you have not seen.
4. **Encode both in the relevant skill/doc**, in assert language ("X must
   always Y"), not as "remember the AUR incident."
5. **Prove the fix and the gate.** Fail-before / pass-after, both outputs
   pasted (`engine/CLAUDE.core.md`, Named constraints; [[prove-it-ship-gate]]
   for live side effects). A gate is proven effective only when a deliberate
   reintroduction of the defect makes it fire (mutation testing); a test
   that only passes proves nothing.

**Steps 3 and 4 land in the same change.** Prose with no code behind it is
the weakest tier of the fix hierarchy and drifts silently; the repo gate is
`scripts/check_codify_has_code.py`. Either fix the code in the same change,
or do not document the rule yet.

## Anti-patterns

- "We checked the one case that broke" (should be every case of that shape).
- "It looks fine now" (checked the surface, not the invariant).
- "The rubric/reviewer allowed this shortcut" — one passing layer is one
  slice of Swiss cheese; the shortcut is still the hole the next case goes
  through.
- Restating the common case as universal ("every exit forces the value to
  zero") when the real rule has an exception class (identity-only exits never
  had a filed value). Model the exception class as its own variant so the
  blanket rule cannot be stated.
- A code path kept "for continuity" that is neither named in the skill nor
  banned nor tightly typed — an untracked escape hatch that happens to look
  rubric-compliant is how the class recurs under a new name.

## Grounding

- Invariant as a predicate over every state → C. A. R. Hoare, "An Axiomatic
  Basis for Computer Programming", *CACM* 12(10) (1969)
  <https://dl.acm.org/doi/10.1145/363235.363259>; Bertrand Meyer, "Applying
  'Design by Contract'", *IEEE Computer* 25(10) (1992)
  <https://se.inf.ethz.ch/~meyer/publications/computer/contract.pdf>. Step 1
  writes the class invariant; step 3 asserts it at runtime.
- Class of defect, not the instance → Chillarege et al., "Orthogonal Defect
  Classification", *IEEE TSE* 18(11) (1992); Google SRE, "Postmortem
  Culture" (2016) <https://sre.google/sre-book/postmortem-culture/>, where
  action items target the systemic cause; Toyota "five whys" (Taiichi Ohno,
  *Toyota Production System*, 1988) is the same move in manufacturing.
- Completeness twin → precision vs. recall, van Rijsbergen, *Information
  Retrieval* (1979); DAMA-DMBOK "completeness" dimension.
- Cases you have not seen → Claessen and Hughes, "QuickCheck", *ICFP* (2000)
  <https://dl.acm.org/doi/10.1145/351240.351266>; Python `hypothesis`.
- Fail-before / pass-after → Kent Beck, *Test-Driven Development: By
  Example* (2002), red then green; Dijkstra, "Notes on Structured
  Programming", EWD249 (1970): testing shows presence, not absence, so a
  test must be seen failing to mean anything.
- Gate effectiveness → DeMillo, Lipton, Sayward, "Hints on Test Data
  Selection", *IEEE Computer* 11(4) (1978), the origin of mutation testing;
  tools: PIT <https://pitest.org/>, `mutmut` for Python.
- Swiss cheese → James Reason, *Human Error* (1990).
- Escape hatches and blanket rules → Yaron Minsky, "Effective ML" (2010),
  "make illegal states unrepresentable"; Alexis King, "Parse, don't
  validate" (2019) <https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/>.
- No external prior art: "steps 3 and 4 in the same change" is a repo-local
  rule. It rests on the reflect fix hierarchy (prose is tier 4) and Gojko
  Adzic's living-documentation argument (*Specification by Example*, 2011),
  and is kept only because `scripts/check_codify_has_code.py` enforces it.
