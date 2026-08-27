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
