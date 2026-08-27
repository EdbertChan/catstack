User types `/principle-outcome-oriented-execution` while planning to
thread a new required field through an existing IPC message type and
every caller that constructs it, via 3 PRs: add the field as optional
with a fallback default, wire callers to start setting it, then delete
the fallback in a follow-up PR later.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-outcome-oriented-execution` invocation above is
the only way it activates. Once invoked: this is a migration at small
scale. Add the field, wire every caller, and delete the fallback in the
same slice — no PR should ship the "optional + fallback" compat-shim
state, even briefly.
