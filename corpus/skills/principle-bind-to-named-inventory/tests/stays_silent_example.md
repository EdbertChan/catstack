A user asks to add a brand-new feature: "can we add sentiment scoring
for earnings-call transcripts? We don't have anything like that
today." No explicit invocation of this skill happens anywhere in the
session — the agent just scopes and builds the new feature.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no prior audit naming existing
scorers/rankers that cover this need, and no complaint that current
weights are arbitrary — even if this skill somehow were invoked, its
content would not apply to a genuinely new capability with no existing
inventory to bind the request to.
