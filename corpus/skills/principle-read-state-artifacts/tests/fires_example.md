User types `/principle-read-state-artifacts`. A session is designing a
babysit loop for a stack of PRs: every 10 minutes it runs `gh pr list`
plus `gh pr view` on each PR to check merge state, appending the results
to its transcript. Meanwhile a cron worker already scans the same queue
every 5 minutes and appends per-PR dispatch state to a JSONL ledger on
disk.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-read-state-artifacts` invocation above is the only
way it activates. Once invoked: this is exactly the described mechanism
— a watcher re-deriving state that a deterministic process already
records. The skill's pattern applies directly: the babysit loop's read
step should fold the ledger (or read a digest file) instead of running
live `gh` sweeps whose output accumulates in the transcript, and the
loop should exit when the ledger reports the stack's terminal
condition.
