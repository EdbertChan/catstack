Writing a Python script that shells out to `git` and parses plain-text
stdout with regexes — no static type system is involved at any point in
the pipeline — and no explicit invocation of this principle skill was
made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, there's no type checker here to exploit as a proof assistant,
so none of the patterns (illegal states, branding, exhaustive matching)
have anything to attach to.
