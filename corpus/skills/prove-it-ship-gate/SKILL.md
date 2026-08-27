---
name: prove-it-ship-gate
description: >
  Auto-trigger when claiming a feature, worker, or integration is done, shipped,
  or working and the Goal includes live side effects (Linear tickets, deploy,
  live mine, external APIs). Unit/fixture tests and UI registration alone are
  not enough — route to prove-it for live evidence before treating the claim
  as settled.
---

# prove-it-ship-gate

Thin routing skill for ship/done claims with live side effects.

Follow Invoker or a locally installed `prove-it` for the shared evidence rule.
This file only adds the ship/done auto-route; it does not replace `prove-it`.

## Rule

When the work under claim has live side effects:

- **Fixture ≠ live.** Unit tests, mocked fixtures, and UI registration Visual
  Proof do not prove the live path ran.
- Before stating done / shipped / working: show **live evidence in the same
  turn**, or prefix the claim with `UNVERIFIED: live path`.
- Do not frame UI Visual Proof (for example worker registration in a settings
  panel) as product e2e of the live side effect.

## Incident

Invoker PRs #10553–#10558 published cross-repo-research after unit + fixture +
UI only; the user forced a live Linear e2e and a reflect afterward.
