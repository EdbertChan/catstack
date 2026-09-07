An agent is adding a fallback around an optional dependency and proposes
`try { loadOptionalModule() } catch {}`. The agent invokes
`/principle-explicit-errors`, names the expected import failure, and replaces
the silent handler with an explicit fallback plus a test for unexpected errors.

A second shape, same skill, no exception in sight. A realized-gains tab
passes "every value traces to a source", then a review pass finds a sell
with no matching cost lot hit a bare `continue`, a table parser returned
zero rows for whole periods, and a period grid stopped at the first source.
The agent invokes `/principle-explicit-errors` before the fix: each of those
paths now raises, logs with the row's context, or emits the row with a
status column (`unmatched`, `unparsed`, `truncated`) and a reason, and the
grader counts expected rows, not only emitted ones.
