`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-guard-the-context-window` invocation.

The agent is about to run a shell command that dumps a 4MB CI log
straight to stdout, planning to eyeball the whole thing in the main
thread to find the one failing test. Before running it, the agent
explicitly invokes `/principle-guard-the-context-window` to load the
full principle.

This skill fires here specifically because of that explicit invocation
-- a large payload heading straight into context with no isolation is
exactly the pattern the skill targets once loaded (redirect to a file
first, grep/jq only the relevant lines, or route it to a subagent),
but no amount of matching prose alone would have triggered it.
