The agent is asked "how many open PRs are there right now?" and
correctly reports 4, having never stated a different number earlier in
the conversation. No explicit invocation of this skill happens
anywhere in the session.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also nothing previously stated being contradicted
— even if this skill somehow were invoked, its content would not apply
to a fresh, first-time answer with no earlier wrong number to flag.
