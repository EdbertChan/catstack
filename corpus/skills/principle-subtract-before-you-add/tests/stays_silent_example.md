A brand-new feature is being built from scratch in an empty module with
no prior implementation, no dead code, and no existing validators
covering this responsibility anywhere in the codebase, and no explicit
invocation of this principle skill was made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, there is nothing to subtract — no redundant validators, no
stub references, no dead weight in this area to remove before building.
