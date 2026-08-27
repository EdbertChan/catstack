`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-bind-to-named-inventory` invocation.

An audit already named three existing scorers (finding-priority mix,
fraud_learning case frequency, recency decay) and said flag types
don't transfer across companies because of exact-string matching. The
user says: "these weights feel arbitrary, I think we need a real
classifier." Before drafting the follow-up plan, the agent explicitly
invokes `/principle-bind-to-named-inventory` to load the full principle.

This skill fires here specifically because of that explicit invocation
— "real classifier" and "arbitrary weights" line up with exactly the
pattern the skill targets once loaded (bind the complaint to the named
`fraud_learning` gap instead of proposing a new sklearn model), but no
amount of matching prose alone would have triggered it.
