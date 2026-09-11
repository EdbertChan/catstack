An agent is deciding whether to add a new color to a UI palette. No exception,
failure path, retry, suppression, or error translation is being designed, so
no explicit invocation of this skill occurs and it stays silent.

An agent is renaming a variable inside a function that already raises
`ValueError(f"expected an ISO date, got {raw!r}")` with the original error
chained. No failure path or message text changes, and the existing message
already names its cause and input, so the skill stays silent.
