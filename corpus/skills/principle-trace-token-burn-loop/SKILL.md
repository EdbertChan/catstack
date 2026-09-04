---
name: principle-trace-token-burn-loop
description: >-
  Apply when analyzing token burn or agent session spend. Prevents mistaking
  the top task_type or prompt_type for the root cause. Forces a trace from the
  session back to the loop script or plan entry point before prescribing a fix.
disable-model-invocation: true
---

# Trace token burn back to the loop script

When a session miner reports a task_type or prompt_type consuming tokens, the
symptom (what the agent was doing) is not necessarily the cause (what kept
re-spawning the agent).

**Why:** session JSONL contains `cwd`, `workflow_id`, and the first user prompt,
but the scheduler name is missing. An unbounded outer loop — a worker
`intervalMs`, a `while true` shell driver, a cron plan, or a plan task with no
iteration limit — can make a cheap plan become an expensive burn.

**Pattern:**

1. Rank spend by task_type / prompt_type, then open one representative session
   file.
2. Read its `cwd` and first user prompt to map it to a plan or workflow.
3. Open that plan or worker file.
4. Look for an unbounded loop:
   - `intervalMs` without a max-tick or max-age bound
   - `while true`, `sleep`, or a cron expression
   - a plan task that calls `submitPlan` on every tick with no cooldown
   - a shell loop driver that re-enters the plan on failure
5. Before adding a worker-level cooldown or a smarter prompt, confirm the
   scheduler is not already responsible for re-running the same plan.
6. If the scheduler is unbounded, the root cause is the loop script / plan entry
   point, not the plan content.

Avoid stopping at the worker that submitted the plan. The worker may be correct
on each tick; the bug is the loop that keeps ticking.
