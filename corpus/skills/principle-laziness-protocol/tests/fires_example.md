`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-laziness-protocol` invocation.

User: "Can you clean up this 40-line function? It works but feels
messy." The agent's first instinct is to introduce a new
`StrategyResolver` class, an interface, and a config-driven dispatch
table for hypothetical future cases nobody asked for. Before doing
that, the agent explicitly invokes `/principle-laziness-protocol` to
load the full principle.

This skill fires here specifically because of that explicit invocation
-- reaching for new layers and interfaces on a "clean this up" request
is exactly the over-engineering trap the skill targets once loaded
(redirect toward deletion, flattening, or the smallest change that
solves the actual problem), but no amount of matching prose alone would
have triggered it.
