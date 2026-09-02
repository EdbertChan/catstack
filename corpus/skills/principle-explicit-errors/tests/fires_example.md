An agent is adding a fallback around an optional dependency and proposes
`try { loadOptionalModule() } catch {}`. The agent invokes
`/principle-explicit-errors`, names the expected import failure, and replaces
the silent handler with an explicit fallback plus a test for unexpected errors.
