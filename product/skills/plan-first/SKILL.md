---
name: plan-first
description: >-
  Front door for work that will span more than one file, review unit, or
  commit. Produces the plan before the first edit: the claim, the done-gate,
  the slice boundaries, the gates that will run, and the base it runs against.
  Names the invariants that apply rather than restating them. Use before
  authoring implementation work, or when a task is about to become a PR stack.
---

# Plan first

Most rework is a constraint discovered late that was knowable early. This
produces the plan while changing the plan is still free.

It carries **no invariants of its own**. Invariants live in `principle-*`
skills, which is why they survive a plan being wrong. This file names them and
stops.

## When this is worth it

Run it when the work will cross a file, a review unit, or a commit. Skip it
for a one-file change with a local check — planning a two-line fix costs more
than the fix.

The tell that it was skipped: a gate rejects the shape of the work rather than
its content ("mixed review units", "changed without a corresponding test
change"). That is a planning failure surfacing as a build failure.

## Step 0. Scan the past decisions on the code you will touch

Before the claim, read what earlier changes to this area decided. For each
file or guard the plan changes:

```sh
git log --oneline -15 -- <file>
gh pr view <number> --json title,body
git log -S '<token>' --oneline
```

The first lists the PR numbers of recent decisions, the second reads the ones
that set the current shape, and the third finds who added the check or rule
you will change.

For a small area, run these inline. For more than a couple of files, or
any plan that removes, reverses, or loosens something, hand this to the
`why` skill's decision-history investigator (a read-only helper agent)
here, not after the diff exists. Record what you found on the `History:` line of the output.

## Step 1. State the claim and the done-gate

One sentence each:

- **Claim** — the single thing a reviewer is being asked to approve.
- **Done-gate** — the command or artifact that passes when the claim holds.

If the done-gate is not a command, say what you will show instead. "It works"
is not a done-gate; `principle-prove-it` will reject it later, so reject it
now while it costs nothing.

Two claims means two slices. Go to Step 2.

## Step 2. Derive the slices before writing any of them

Delegate to `split-scope`. Decide the boundaries from what the repo's own
review units are, not from what is convenient to write.

Name, per slice: the claim, the review unit, and why it cannot merge with its
neighbour. A slice that needs a sibling's file to pass its own gates is not a
slice — it is one slice pretending to be two.

Order them so evidence precedes the change it justifies: a repro before its
fix, a rule before the gate that enforces it, a foundation before the
behavior on top.

## Step 3. List the gates now, at the scope they will run

This is the step that pays for the whole playbook.

Find the repo's gate runner (a preflight script, a CI workflow, a documented
check list) and write down which gates each slice will trip. Then check each
one's **scope**: a gate invoked with a wider default than the slice can report
clean on work it never compared.

A gate you discover at publish time is a re-split. A gate whose scope you
never checked is a false pass.

## Step 4. Pin the base

Name the ref every slice is planned against, and confirm it is current. For a
stack, that base moves: if the bottom merges while the top is in flight, and
the merge was a squash, the upper slices still carry commits that are no
longer ancestors, and every one of them conflicts.

Decide now whether the stack tolerates the base moving, or whether it must
land as a unit.

## Step 5. Name the invariants, do not restate them

List the `principle-*` skills this work triggers, each with the decision it
changes. A principle named with no decision behind it was name-dropped.

If a principle would forbid the plan, the plan changes here — not after the
diff exists.

## Step 6. Pick the products, then stop planning

Name which procedures run and in what order — `how` and `why` before editing
unfamiliar code (Step 0 already ran the history part of `why`), `alternatives-considered` plus `spike-and-validate` for a
decision expensive to reverse, the repo's verification and PR skills at the
end.

Then stop. A plan that keeps growing is avoiding the work.

## Output

```text
History:   <PRs read> — <decision each one made that this plan keeps or changes>
Claim:      <one sentence>
Done-gate:  <command, or what you will show>
Slices:     <n>  — <unit> · <claim> · <why separate>
Gates:      <gate> at <scope>
Base:       <ref> — current as of <check>
Invariants: <principle-name> → <decision it changed>
Products:   <ordered list>
Unknowns:   <what would change the plan if it turns out otherwise>
```

`Unknowns` is not optional. A plan with no unknowns has not been examined.

## Do not

- Restate an invariant's content here. Name it and link it.
- Plan a one-file change with a local check.
- Keep planning after Step 6.
- Treat a gate's default scope as the slice's scope.
