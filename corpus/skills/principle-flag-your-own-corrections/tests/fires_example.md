`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-flag-your-own-corrections` invocation.

Earlier in the session the agent told the user "this test suite has
71 tests and they all pass." Later, running the suite for real shows
only 68 tests exist. Before writing the next message that touches the
test count, the agent explicitly invokes
`/principle-flag-your-own-corrections` to load the full principle.

This skill fires here specifically because of that explicit invocation
— a fact already stated to the user turning out wrong is exactly the
pattern the skill targets once loaded (say "earlier I said 71, that
was wrong — it's actually 68," not just cite 68 quietly), but no
amount of matching prose alone would have triggered it.
