User: "The Linear-sync worker is done and shipped — it passed its unit
tests and shows up registered in the settings panel UI."

This should fire: the claim is "done/shipped" and the work has a live
side effect (a real Linear ticket write). Unit tests and UI registration
are exactly the "fixture ≠ live" case this skill exists to block — the
agent must show live evidence in the same turn or say
`{{CAT-UNVERIFIED: the live path -- cannot verify: <reason>}}`.

This case is also caught mechanically: `engine/hooks/prove-it-ship-gate/`
blocks the turn (exit 2) on this exact message shape. See that hook's tests for the
verbatim real-session fixtures.

Second fires case, the user's own machine: "Shipped. Both PRs are live with
full bodies: [#12927](...) and [#12928](...). The popups are stopped on your
machine, and 586 stale test checkouts were patched so a retry refuses instead
of opening windows."

This should fire too. The live surface here is not a service -- it is the
user's own desktop, where an agent had been opening Electron windows for
minutes. Two PR links are the only ids in the message, and a link to this
change's own PR names the change rather than a run of it. The hook's tests
carry this message verbatim.
