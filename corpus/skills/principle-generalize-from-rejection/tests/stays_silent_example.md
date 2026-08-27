A lint check fails once because of a genuine one-off typo (`improt`
instead of `import`). The agent fixes the typo and the check passes on
the very next run -- no second rejection of the same class ever occurs
in this session, and no explicit invocation of this skill happens
anywhere either.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no repeated rejection to generalize from --
even if this skill somehow were invoked, its content would not apply
to a single, already-resolved mechanical failure.
