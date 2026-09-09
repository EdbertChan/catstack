A user asks which name reads better for a local variable in a helper they are
writing, `retryCount` or `attempts`, and the agent gives an opinion.

This skill stays silent. Auto-firing is driven by the presence of a claim to
hold evidence against, and there is none here: a naming preference asserts
nothing about behavior, system state, history, or a cause. There is no
"this is fixed", no "the cause is X", no hedge about code that could be
checked by running something.

Firing here would be the skill misbehaving rather than working — demanding a
command run and pasted output before answering a style question is the
false-positive this fixture exists to pin down.
