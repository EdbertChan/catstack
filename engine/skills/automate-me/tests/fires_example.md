User types `/automate-me` and says: "mine my last few weeks of sessions
and turn how I work into a skill."

This fires: `disable-model-invocation: true` means the model never reads
this skill's `description:` to decide whether to auto-invoke it — the
only way `automate-me` activates is this explicit slash-command
invocation, regardless of what the request's wording is. (Note:
`automate-me`'s own description also lists autonomous "must invoke"
conditions — e.g. the same complaint type appearing twice — but those
can never actually fire on their own given the flag; that's a separate,
pre-existing inconsistency in this skill's own authoring, not something
this fixture can paper over.)

The mined session log will show timestamps and specific incidents (a
session date, a quoted correction) as the raw evidence, but none of
that survives into the produced `<handle>-mode` skill: a trailing
provenance clause naming when or how the pattern was noticed is a
Guardrails violation even in a fresh, from-zero run, not only on an
update.
