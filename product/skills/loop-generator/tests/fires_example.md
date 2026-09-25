User says: "I want a reusable loop that keeps retrying our flaky
integration-test job until it passes, and stops after 3 identical
failures so I can look at it myself."

This matches the trigger phrase "retry failed jobs until they pass" and
asks for a recurring watch/retry behavior, so the skill runs its
interview (loop_name, goal, target_discovery_command, fail_condition_rule,
write_mode, etc.) before drafting the instruction doc + driver script pair.

During the interview the skill also asks whether a `state_artifact` exists
— e.g. a CI status file or ledger a worker already maintains. If the user
answers yes, the generated doc names that artifact in `Real target` and
`Evidence sources`, the per-round read folds it instead of re-querying the
live source, and the `Exit conditions` section states the terminal
condition that ends the watch.
