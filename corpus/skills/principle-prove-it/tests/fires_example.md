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

A third shape, from the gate-blame rule. An agent's tool call is refused by a
hook and the reply says "the hook is wrong, it misfired on a read-only
command." Nothing was read this turn: not the hook's detector, not the
condition it tests, not the input it judged. This skill fires on that claim
shape too, because blaming a gate is a causal claim like any other — it needs
the rule quoted with its `file:line` next to the input, or a `{{CAT-UNVERIFIED}}` tag naming the blocker. The
reversal that usually follows ("actually it doesn't block that") is a second
claim needing its own evidence, not a correction that inherits the first
one's. Chesterton's fence names the failure: the fence came down before
anyone read why it went up.
