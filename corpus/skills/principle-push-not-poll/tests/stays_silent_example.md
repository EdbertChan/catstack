A session is designing a headless CLI wrapper that polls a backgrounded
deploy script every 10 seconds, re-sending the full accumulated log on
each check — exactly the mechanism this skill names. The user never
types the skill's own slash command anywhere in the session.

Stays silent: this skill has `disable-model-invocation: true`, so
nothing about the description or the situation itself can trigger it —
only its own explicit invocation would. Even though the poll-loop
pattern is present, without that explicit invocation the skill never
activates.
