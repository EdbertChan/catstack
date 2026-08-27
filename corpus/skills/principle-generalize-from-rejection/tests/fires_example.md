`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-generalize-from-rejection` invocation.

A PR-body validator rejects a submission with "Invalid review unit:
engine-runtime. Expected one of product, cleanup, policy, proof, docs."
The agent fixes it, submits a second PR body, and the SAME validator
rejects it again for the exact same "invalid review unit" reason on a
different value. Before drafting a third attempt, the agent explicitly
invokes `/principle-generalize-from-rejection` to load the full
principle.

This skill fires here specifically because of that explicit invocation
-- two rejections of the same class in one session is exactly the
pattern the skill targets once loaded (stop and check every other PR
body about to be submitted for the same mistake, instead of guessing a
third value), but no amount of matching prose alone would have
triggered it.
