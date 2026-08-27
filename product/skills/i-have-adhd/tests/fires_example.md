User types: `/i-have-adhd`

Then asks: "walk me through fixing the failing auth test."

This skill is `disable-model-invocation: true`, so it only activates on
the explicit `/i-have-adhd` slash command (or staying on until the user
says "stop adhd mode") — not from matching the description text alone.
Once invoked, the assistant leads with the next concrete action, numbers
the steps, restates progress each turn, and drops preamble/closers.
