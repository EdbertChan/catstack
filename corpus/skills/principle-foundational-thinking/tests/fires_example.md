`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-foundational-thinking` invocation.

User: "Add a `retries` field to the job table, and also write the code
that decrements it and marks the job failed when it hits zero." Before
writing either mutator, the agent explicitly invokes
`/principle-foundational-thinking` to load the full principle.

This skill fires here specifically because of that explicit invocation
-- two code paths that could each finalize the same job row is exactly
the sequential-composition pattern the skill targets once loaded (name
who owns the terminal transition before writing either mutator), but no
amount of matching prose alone would have triggered it.
