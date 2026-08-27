User: "Rename this local variable from `x` to `userCount` for clarity."
No explicit invocation of this skill happens anywhere in the session --
the agent just makes the rename.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no new data structure, no shared mutable
state, and no sequencing decision -- even if this skill somehow were
invoked, its content would not apply to a pure single-line rename.
