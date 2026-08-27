`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-encode-lessons-in-structure` invocation.

For the third time this month, the agent is about to tell a reviewer
"remember to squash your commits before merging" in a PR comment,
after saying the exact same thing in two earlier PRs from the same
contributor. Before writing that comment a third time, the agent
explicitly invokes `/principle-encode-lessons-in-structure` to load
the full principle.

This skill fires here specifically because of that explicit invocation
— a recurring instruction repeated as text is exactly the pattern the
skill targets once loaded (encode it as a lint rule or CI check instead
of a fourth reminder), but no amount of matching prose alone would have
triggered it.
