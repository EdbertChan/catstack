User says: "The release-handover playbook says 'ping the on-call channel'.
We renamed that channel to #release-oncall — update the sentence."

This is a one-line wording fix inside a step body. No step is added or
removed, no binding changes, no level or evidence key moves, no trigger
phrase is claimed, and nothing needs installing. Working an eight-step
authoring list — trigger collision check, rule id binding, level choice,
gate binding, fixture pair, validator run, routing proof — would be pure
overhead for an edit that changes no step and no binding.

Touching a file under `playbooks/` is not the trigger. Changing what the
steps are, or what they bind to, is.
