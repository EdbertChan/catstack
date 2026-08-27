A new required field must be threaded through an existing IPC message
type and every caller that constructs it. The plan on the table is 3
PRs: add the field as optional with a fallback default, wire callers to
start setting it, then delete the fallback in a follow-up PR later.

Trigger: this is a migration at small scale. Add the field, wire every
caller, and delete the fallback in the same slice — no PR should ship
the "optional + fallback" compat-shim state, even briefly.
