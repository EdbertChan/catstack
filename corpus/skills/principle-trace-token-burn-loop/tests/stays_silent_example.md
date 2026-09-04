A session miner reports that `scratch` -> `repair-filing-delete` is consuming
nearly all Codex token budget. The agent opens a representative session, maps its
`cwd` to a plan file, sees a `continue-babysit-worker-loop` task with no
iteration limit, and checks the shell loop driver for `while true` / `sleep`
logic. The agent then proposes bounding or adding a cooldown to the loop entry
point, not the worker's plan submission.

This should stay silent because the agent has already traced the loop script
and identified the real root cause.
