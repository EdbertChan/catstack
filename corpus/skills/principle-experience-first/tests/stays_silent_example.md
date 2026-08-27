A backend job is failing intermittently with a stack trace, and the
task is purely to find and fix the root cause of the crash — no
user-facing behavior, UI, or feature-scope decision is involved. No
explicit invocation of this skill happens anywhere in the session.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no product/UX/feature-scope tradeoff — even
if this skill somehow were invoked, its content would not apply to a
pure debugging task, which is a different principle's territory.
