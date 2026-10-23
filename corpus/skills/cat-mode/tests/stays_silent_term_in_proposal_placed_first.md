`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent proposed two fixes in a chart. One bar is labelled "setup".
The user asks: "so the setup is just the job's prep list? why suggest
it again in fix 1 and 2?"

User: so the setup is just the job's prep list? why suggest it again in fix 1 and 2?
Assistant: Yes, it already exists; the fix does not add it. Fix 2 only moves when it runs, so it overlaps the other build instead of waiting for it.

This rule stays silent. The first sentence says the term already exists
and is not being added; the mechanic comes second; no code map was given
because none was asked for.
