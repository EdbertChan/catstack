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

Mechanical twin: with `CATSTACK_EXPLICIT_FAILURES=1`, `engine/hooks/explicit-failures` fires on the same shapes as they are written (`except: pass`, `catch {}`, a bare `continue` under `if not lots[t]:`), one advisory line per hit, exit 0.

A third shape. A reflect pass proposes a new rule, "a loop must prove it
reached the last filing." The agent invokes `/principle-explicit-errors`,
finds the Grounding section, and writes the rule in the field's term
instead: a record-count reconciliation against the filing index (control
total), citing the SRE Workbook completeness SLO, and marks the cap case
`truncated` the way a paginated API returns `IsTruncated`.
