A brand-new feature is being built from scratch in an empty module with
no prior implementation, no dead code, and no existing validators
covering this responsibility anywhere in the codebase.

Does not trigger: there is nothing to subtract — no redundant
validators, no stub references, no dead weight in this area to remove
before building. The skill's pattern applies when evolving an existing
system, not when starting from a clean slate.
