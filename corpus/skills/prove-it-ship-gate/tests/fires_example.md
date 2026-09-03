User: "The Linear-sync worker is done and shipped — it passed its unit
tests and shows up registered in the settings panel UI."

This should fire: the claim is "done/shipped" and the work has a live
side effect (a real Linear ticket write). Unit tests and UI registration
are exactly the "fixture ≠ live" case this skill exists to block — the
agent must show live evidence in the same turn or say
`UNVERIFIED: live path`.

This case is also caught mechanically: `engine/hooks/prove-it-ship-gate/`
blocks the turn (exit 2) on this exact message shape. See that hook's tests for the
verbatim real-session fixtures.
