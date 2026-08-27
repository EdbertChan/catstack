A PR-body validator rejects a submission with "Invalid review unit:
engine-runtime. Expected one of product, cleanup, policy, proof, docs." The
agent fixes it, submits a second PR body, and the SAME validator rejects it
again for the exact same "invalid review unit" reason on a different value.

This is the second rejection of the same class in one session — the skill
should fire: stop, read what the validator is actually enforcing (a fixed
taxonomy), and check every other PR body about to be submitted for the same
mistake, instead of guessing a third value and resubmitting.
