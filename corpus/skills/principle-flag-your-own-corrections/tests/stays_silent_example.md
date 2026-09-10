A user asks the agent to rename a function from `fetchRows` to `loadRows` and
update its three call sites. The agent makes the edits, runs the module's
tests, and reports them passing.

This skill stays silent. Nothing the agent previously told the user has turned
out to be wrong: there is no earlier claim, no number that moved, no check
that was skipped and later found hollow. Every obligation the skill carries
presupposes a prior statement to correct, and there is none here.

Auto-firing is driven by a correction taking shape, not by the topic being
technical or by tests being run. A turn that states a fresh, verified result
for the first time is the ordinary case this principle is not about — firing
here would ask the agent to retract something it never said.
