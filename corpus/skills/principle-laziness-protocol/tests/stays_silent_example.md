User: "Add a null check here before we call `.trim()` on this string, since
it can come back undefined from the API."

A single, necessary guard clause directly required by a real bug report —
not a refactor, not an abstraction decision, not a diff-size judgment call.
There's nothing to be lazy about here; just add the check. The skill should
stay silent.
