---
name: maintain-verification-skill
description: >-
  Periodic pass that keeps a project's verification skill and feature map
  honest: parallel source readers per feature, one live session driving every
  feature, at most one set of proven corrections. Use for
  /maintain-verification-skill or "audit the verify skill".
disable-model-invocation: true
---

# Maintain a verification skill

Adapted from `maintain-verification-skill` in the `pstack` plugin of
[cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack/skills/maintain-verification-skill)
(MIT, Lauren Tan). Changes: publishing needs the user's ask, subagent
citations carry a confidence tag and a ref, and a check that could not run
reports unchecked.

A feature map goes stale the moment the app changes. This is the upkeep loop
for a skill made by `create-verification-skill` (or any project-local
verification skill with a feature map). The unit of rigor is the feature, not
every sentence: cover every feature file from source and exercise every
feature live, without proving every bullet.

It is explicit-only (`disable-model-invocation: true`) because one run fans
out subagents and drives a live app. Type `/maintain-verification-skill`.

## Outcomes

Pick one and say which:

- **clean**: every feature got source and live coverage; nothing worth
  shipping. No branch, no PR.
- **changed**: proven doc, harness, or map corrections are ready to ship.
- **blocked**: coverage could not finish or a proven fix could not ship
  safely. Say exactly what blocked it.

## Edit scope

Edit only the verification skill's own directory (its `SKILL.md`, `features/`,
and any harness scripts it owns). Never edit product code during a run. A
behavior the map describes that the app no longer does is either doc drift
(fix the map) or a product regression (report it, do not paper over it in
docs).

## Pass

0. **Locate the target.** Find the project-local skill whose body has launch
   and drive sections and a feature map (usually `.cursor/skills/verify-*/`).
   Several candidates: ask which one. None: stop and point at
   `create-verification-skill` instead of inventing a target.

1. **Index hygiene.** Read the feature map README and list its sibling files.
   Fix missing, extra, duplicate, or dead entries. Keep it light; no generated
   inventory.

2. **Source wave.** One read-only subagent per feature file, launched
   together. Each explains "how does this user-facing feature work?" from
   source, flags likely doc drift with citations, and returns one concise
   live-verification recipe. Children never drive the app and never edit
   files. Each brief asks the child to tag every `file:line` as
   "read-confirmed" (it opened the real reference and traced it) or
   "name-matched" (it assumed from the name), and to name the ref it read
   (working tree, `HEAD`, or `origin/<base>`). Return shape: feature summary,
   source entry points, likely drift or none, one recipe. Treat a
   name-matched citation as unchecked until you read it yourself.

3. **Reconcile.** Every feature file has a returned summary. Merge overlapping
   recipes into as few app states as practical. Spot-check cited drift; do not
   re-prove clean claims. Sweep recent churn for user-facing surfaces missing
   from the map, and require a concrete source path before calling one
   missing.

4. **Live pass.** Required even when source looks clean. The coordinator owns
   all driving and follows the verification skill's own launch model: one
   long-lived instance driven one feature at a time for servers and UIs, or a
   fresh isolated session per drive for short-lived CLIs (the skill's Launch
   section decides). Exercise every feature at least once and hold three
   rules the whole pass, whatever fails:
   1. Never drive an instance you have not health-checked since it last did
      something surprising. Run doctor before the first drive, on each fresh
      session where sessions are the unit, and again after any failed drive.
      Where doctor cannot see the failure (a stuck UI on a healthy process),
      reset to a known state or relaunch.
   2. Evidence captured so far survives every cleanup, checked at its named
      location, not assumed.
   3. Nothing a drive started outlives its usefulness. Clean failed-attempt
      leftovers whether the session is stuck, exited, or shared (for a shared
      instance, clean the leftovers, not the instance).

   A doctor failure caused by skill drift is drift: fix it within edit scope
   and retry once, restarting only what the fix invalidated, before calling
   the pass `blocked`. A feature that cannot be reached is
   `verified-unreachable` only with the concrete prerequisite (auth,
   entitlement, OS, external state) and the route attempted; if the map omits
   that prerequisite, that is drift. A step that could not run is reported
   unchecked with its reason, never as pass. Any harness fix from triage is
   re-driven live before it ships. Final teardown happens after the last
   drive of the run, including those re-drives, so nothing outlives the run
   (evidence stays).

5. **Triage.** Wrong or missing user-view description: doc drift, fix it.
   Working behavior the harness cannot drive: harness gap, fix it (scripts
   executable, invocation shown in the skill body). App behavior that is
   actually broken: product gap; record it for the user and keep it out of
   the fix.

6. **Ship or stop.** For `changed`: re-read every changed file, then stop and
   say the corrections are ready. Commit, push, or open a PR only when the
   user asked for it, using `draft-pr`. For `clean` or `blocked`: no branch,
   no PR; report the outcome and the coverage honestly.

Keep short run notes (features covered, unreachable prerequisites, confirmed
drift, outcome) in a scratch location. Do not commit them.
