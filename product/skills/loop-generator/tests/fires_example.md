User says: "I want a reusable loop that keeps retrying our flaky
integration-test job until it passes, and stops after 3 identical
failures so I can look at it myself."

This matches the trigger phrase "retry failed jobs until they pass" and
asks for a recurring watch/retry behavior, so the skill runs its
interview (loop_name, goal, target_discovery_command, fail_condition_rule,
write_mode, etc.) before drafting the instruction doc + driver script pair.
