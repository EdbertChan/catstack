User: "Add a null check here before we call `.trim()` on this string,
since it can come back undefined from the API." No explicit invocation
of this skill happens anywhere in the session -- the agent just adds
the check.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no refactor, no abstraction decision, and no
diff-size judgment call here -- even if this skill somehow were
invoked, its content would not apply to a single, necessary guard
clause required by a real bug report.
