A session is designing a babysit loop that re-runs `gh pr list` and
`gh pr view` every 10 minutes to re-derive merge state a cron worker
already records to a ledger — exactly the mechanism this skill names.
The user never types the skill's own slash command anywhere in the
session.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. Even though the re-derive
pattern is present, without that explicit invocation the skill never
activates.
