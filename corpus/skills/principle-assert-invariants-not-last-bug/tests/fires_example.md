`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-assert-invariants-not-last-bug` invocation.

A code-review bot flagged a duplicate row for ticker "AUR" in the
holdings table. The fix ships as `if ticker == "AUR": dedupe()`. Two
weeks later the same duplicate-row bug appears for ticker "SERV" and
sails through review because the fix only patched the AUR case. During
the `/reflect` session that follows, the flow explicitly invokes
`/principle-assert-invariants-not-last-bug` to load the full principle
before writing the real fix.

This skill fires here specifically because of that explicit invocation
— the commit message reading like "fix dedupe for AUR" is exactly the
pattern the skill targets once loaded, but no amount of matching prose
alone would have triggered it.

A second shape, same skill. A realized-gains tab is graded "every value
traces to a source" and passes. A `/reflect` pass later finds that a
sell with no matching cost lot hit a bare `continue` and never reached
the tab, a table parser returned zero rows for several periods, and a
period grid stopped at the first filing instead of the last. Every
check had asked "did we invent?" and none had asked "did we drop?".
The flow explicitly invokes `/principle-assert-invariants-not-last-bug`
to name the class and its omission twin before the fix; the rules for how
a hard row ships (status column plus reason, never a bare `continue`)
live in `principle-explicit-errors`, which the flow loads alongside it.

This is the same explicit-invocation trigger: the fix's own shape (a
row that disappeared instead of shipping with a status) is what the
principle names, but only the `/` invocation loads it.

A third shape. A fix lands with a new gate and a test that passes. The
flow invokes `/principle-assert-invariants-not-last-bug`; step 5 and the
Grounding section (DeMillo, Lipton, Sayward on mutation testing) send the
agent back to reintroduce the defect on purpose and show the gate firing
before the fix is called proven — a test that only passes proves nothing.

A fourth shape, from the Related section. The proposed fix is an assertion
that rejects a malformed status value at runtime. Once this skill is loaded,
its link to `principle-type-system-discipline` routes the agent to ask the
stronger question first: can the type stop that value from being constructed
at all? The assertion is the fallback for what the types cannot express, not
the first reach. A slice that adds a runtime guard where a narrowed type would
have worked is still the last-bug shape, one level up.
