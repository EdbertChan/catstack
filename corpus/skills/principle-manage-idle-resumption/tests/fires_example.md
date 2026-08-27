`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-manage-idle-resumption` invocation.

The agent is about to kick off an overnight CI-repair loop that will
poll a build queue every 15 minutes for the next 6 hours, resuming the
same growing session thread each time. Before starting it, the agent
explicitly invokes `/principle-manage-idle-resumption` to load the full
principle.

This skill fires here specifically because of that explicit invocation
-- a multi-hour polling loop with wall-clock idle gaps between checks is
exactly the pattern the skill targets once loaded (compact before the
gap, or switch to a detached poller that reports back once), but no
amount of matching prose alone would have triggered it.
