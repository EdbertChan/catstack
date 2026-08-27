A user is mid-session on a checkout-flow bug fix. After the fix lands,
they explicitly say "great, now also add a test for the discount-code
path while we're here" — a related, expanding, but user-directed
request within the same feature area — and no explicit invocation of
this principle skill was made.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. And even if it had been
invoked, the human is steering each expansion and confirming it as it
arrives, which the skill explicitly distinguishes from silent,
agent-discovered scope drift.
