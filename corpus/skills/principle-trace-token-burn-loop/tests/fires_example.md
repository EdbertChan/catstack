A session miner reports that `scratch` -> `repair-filing-delete` is consuming
nearly all Codex token budget. The agent concludes the fix is to add a cooldown
to the worker that files the investigative plan, and does not open the plan file
or the shell loop driver that keeps re-entering the same task on every tick.

This should fire `principle-trace-token-burn-loop` because the agent treated the
symptom (repeated scratch plans) as the root cause without tracing the loop
entry point that re-spawns them.
