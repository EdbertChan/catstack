A user asks for a new gate plus the rule it enforces plus scenarios proving
both. That is a corpus rule, an engine script, and test data — three review
units and at least two commits — and the agent is about to open the first file.

This skill fires. Its description targets work crossing a file, review unit,
or commit, and it auto-fires because the only useful moment to plan is before
the first edit; a slice boundary named after the diff exists is a re-split,
not a plan.

Once loaded it forces the cheap decisions now: the claim and done-gate per
slice, the review units from `split-scope`, the gate list **at the scope each
gate will actually run**, and the base ref. The real failure it prevents was
observed: a preflight rejected `engine-runtime and corpus-lesson mixed in one
PR` after the work was written, and separately a coverage gate reported `ok`
for a stacked slice it had never compared because it ran at its default scope.
Both were knowable at Step 3.
