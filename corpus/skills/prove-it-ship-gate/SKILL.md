---
name: prove-it-ship-gate
description: >
  Auto-trigger when claiming a feature, worker, or integration is done, shipped,
  or working and the Goal includes live side effects — an external service
  (Linear tickets, deploy, live mine, external APIs) or the user's own machine,
  session, or screen (an e2e or Playwright run, an Electron window, a popup on
  their desktop). Unit/fixture tests and UI registration alone are not enough
  — route to prove-it for live evidence before treating the claim as settled.
---

# prove-it-ship-gate

Thin routing skill for ship/done claims with live side effects.

Follow Invoker or a locally installed `prove-it` for the shared evidence rule.
This file only adds the ship/done auto-route; it does not replace `prove-it`.

## Rule

The live surface is whatever the work's success actually shows up on. Two
families, and the second is as binding as the first:

- an **external side effect** — a Linear ticket written, a deploy landed, a
  live mine hit, an external API called;
- the **user's own machine, session, or screen** — an e2e or Playwright suite,
  an Electron window, a popup on their desktop. A window opened on the user's
  machine is as real a side effect as a ticket write.

When the work under claim has live side effects:

- **Fixture ≠ live.** Unit tests, mocked fixtures, and UI registration Visual
  Proof do not prove the live path ran. Each layer proved separately is not
  the property proved.
- **Your own PR is not a receipt.** The number or the link of the pull request
  that carries this change names the change, not a run of it.
- **"I chose not to run it" is not a blocker.** A blocker is a thing that made
  the run impossible, named. If the real path was runnable and you did not run
  it, you are not done — run it.
- Before stating done / shipped / working: show **live evidence in the same
  turn**, or tag the claim `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}`.
- Do not frame UI Visual Proof (for example worker registration in a settings
  panel) as product e2e of the live side effect.

## Mechanical enforcement

The same-turn check is a Stop hook, `engine/hooks/prove-it-ship-gate/`
(installed by `install.sh`). It blocks the turn when a done/shipped/live claim sits
near a live-side-effect noun from either family with no chaseable evidence
(a link to this change's own PR is not one), no live command this turn,
and no well-formed `{{CAT-UNVERIFIED}}` tag. This file keeps the judgment half: deciding
whether the work really has live side effects.

## Incident

Invoker PRs published cross-repo-research after unit + fixture +
UI only; the user forced a live Linear e2e and a reflect afterward.

## Related

If the claim isn't done/shipped but repeated failed attempts on one problem within a live session, that's `narrow-the-scope`, not this skill.

If a grading/validation board came back FAIL or NEEDS_WORK, or the user says "/thrash", that's `thrash-reflect-automate`.
