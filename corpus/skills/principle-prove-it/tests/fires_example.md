An agent has just edited a retry handler and is about to write "this fixes
the duplicate-write bug" into a PR body. Nothing ran this turn: no repro, no
test, no command output. The agent never types a slash command.

This skill fires on the claim shape itself. Unlike the other `principle-*`
skills, it does not carry `disable-model-invocation: true`, so its
`description:` is loaded and the model can match it — which is the whole
point: a gate that only works when someone remembers to name it is not a
gate. A fix claim with no evidence in the same message is exactly what the
description targets, and once loaded the skill supplies both the three
accepted evidence forms and the routing table that sends the agent to `how`
to find which artifact to exercise.

The same auto-fire path covers the hedge case: "this should work" is a
trigger to run the check, not a softer way to state the claim.
