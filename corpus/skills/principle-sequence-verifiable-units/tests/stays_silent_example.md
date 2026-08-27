A PR adds a new list, its builder function, and a registration-assertion
test together in one slice. Nothing is wired into a live caller yet, but
the three pieces are meaningless apart — the builder can't be verified
without the list or the assertion — and no explicit invocation of this
principle skill was made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, this is the documented edge case where splitting isn't free —
the slice already ends in a checkable, inert state, and breaking it up
would ship an unusable, unverified builder.
