`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-report-the-disqualifier` invocation.

The agent has drafted an eval write-up whose headline reads "agent success
rate rose from 61% to 88% after the retrieval change." Two facts sit in the
last paragraph, after the tables and the recommendation: a scoring bug was
found and fixed halfway through, and the pre-fix reading of the same
headline was 63%; and the 88% counts runs that only succeeded after the
retry budget was exhausted and the harness restarted them. The cost per run
is frozen at one assumed value that appears in the metric expression and was
never swept. Before sending the write-up, the agent explicitly invokes
`/principle-report-the-disqualifier` to load the full principle.

This skill fires here specifically because of that explicit invocation
-- a causal claim carrying its own reversal, its own absorbing state, and an
unvaried constant, all of them placed after the conclusion, is exactly the
pattern the skill targets once loaded (state the observation that would
refute the claim, grade each claim measured/inferred/conjecture beside the
claim, add a survived column for the exhausted-budget runs, report the
headline under both readings with the sign, and name the cost value at which
the conclusion reverses), but no amount of matching prose alone would have
triggered it.
