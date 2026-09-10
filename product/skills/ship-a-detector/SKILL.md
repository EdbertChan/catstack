---
name: ship-a-detector
description: >
  Author a hook or gate detector end to end: the seven defect kinds this
  repo keeps re-shipping, then the install, test, README, and inventory
  wiring a detector is not finished without. Trigger before writing or
  widening anything under engine/hooks/ or a scripts/check_*.py gate —
  a new PreToolUse/Stop/UserPromptSubmit hook, a new detector inside an
  existing hook, or a regex change to one that already ships.
---

# ship-a-detector

Use this before writing or widening a detector — a hook under
`engine/hooks/`, or a CI gate under `scripts/check_*.py`. Both decide
"does this input match the bad thing", and both break the same seven ways
here.

## Why this exists

Measured on this repo's own history: 65 of 185 merged PRs touch
`engine/hooks/`, 13 of 28 hooks needed post-ship repair, and 37 PRs did
nothing but repair a shipped detector. `diu-stop` took 8, `pr-schema-gate`
7, `wrong-check-reflect` 6, `scope-lock` 4. `gh-write-verification` hit two
separate known kinds in three days. None of those were new problems; each
was a kind already fixed in another hook.

## The playbook

Read and copy [playbooks/detector-lifecycle.md](playbooks/detector-lifecycle.md)
before any task-specific work. It is a verbatim ordered list: paste all 20
steps into your todolist first, then work them. A step that does not apply
stays in the list marked `skip: <reason>` — deleting it is how a kind gets
re-shipped.

The same list covers both jobs. A new hook works every step. A widening of
a shipped detector skips the wiring tail with reasons and still works the
detection steps, because 37 of this repo's repair PRs were repairs of
detection, not of wiring.

## Two rules that outrank the list

- Every numbered step rests on something a reader can check for themselves:
  a named principle or established practice (fail fast, poka-yoke,
  fail-safe vs fail-secure, a state machine, a canary), or a property of
  this repo they can go look at — a file, a gate, a test name, a measured
  count. Never a PR number, a SHA, or the story of the session that hit it;
  history is not checkable and it goes stale. If you add a step, name that
  basis in the step itself — a step invented from a guess is the thing this
  repo already tried.
- The list ends by calling the installed `make-pr` skill. `make-pr` opens
  the PR; it does not own the install, README, or inventory steps. Those
  are steps 14–18 here, because that is measurably where this repo breaks:
  14 of this repo's 34 hooks have no `docs/ecosystem.md` row.
