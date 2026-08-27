User: "Can you clean up this 40-line function? It works but feels messy."

The agent's first instinct is to introduce a new `StrategyResolver` class,
an interface, and a config-driven dispatch table to make it "more
extensible" for hypothetical future cases nobody asked for.

This is exactly the over-engineering trap the skill exists to stop: it
should fire and redirect toward the smallest change that solves the actual
problem (deletion, flattening, consolidating the one repeated decision) —
not new layers, interfaces, or signal-threading for a future that hasn't
arrived.
