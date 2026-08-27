A backend job is failing intermittently with a stack trace, and the task
is purely to find and fix the root cause of the crash — no user-facing
behavior, UI, or feature-scope decision is involved.

This skill should NOT fire: there is no product/UX/feature-scope tradeoff
here, just a debugging task. Fixing a crash isn't a delight-vs-convenience
decision — it's correctness work, which is a different principle's
territory (root-cause fixing), not this one's.
