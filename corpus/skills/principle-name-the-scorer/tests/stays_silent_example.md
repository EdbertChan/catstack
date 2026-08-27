User: "What does this one function, `computeLateFee`, return for an
invoice that's 10 days overdue?" No explicit invocation of this skill
happens anywhere in the session -- the agent just answers.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no second scorer in the picture and no
provenance ambiguity between two ranking systems -- even if this skill
somehow were invoked, its content would not apply to a single
self-contained function with one clear numeric output.
