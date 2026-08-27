A user asks, for the first time, "can you rename this variable from `x`
to `userCount` for clarity?" — a one-off naming preference with no
prior instance. No explicit invocation of this skill happens anywhere
in the session — the agent just makes the rename.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also nothing recurring yet — even if this skill
somehow were invoked, its content would not apply to a single
first-time request, since it targets catching yourself repeating the
same instruction a second time, not any individual piece of feedback.
