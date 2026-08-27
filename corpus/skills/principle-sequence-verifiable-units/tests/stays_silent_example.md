A PR adds a new list, its builder function, and a registration-assertion
test together in one slice. Nothing is wired into a live caller yet, but
the three pieces are meaningless apart — the builder can't be verified
without the list or the assertion.

Does not trigger: this is the documented edge case where splitting isn't
free — the slice already ends in a checkable, inert state, and breaking
it up would ship an unusable, unverified builder. Keeping them together
is the correct call here, not a batching violation.
