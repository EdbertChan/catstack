---
name: alternatives-considered
description: >-
  Produce the real option set for a decision before committing to the first
  shape that came to mind. Use before a design, a schema, a naming or format
  choice, or any change expensive to reverse. Every option is labeled
  considered (cited) or invented (untested); invented options route to
  `spike-and-validate` before they can decide anything.
---

# Alternatives considered

One attempt at a hard design locks in the first shape the model thought of.
This produces the option set, with each option honest about where it came
from.

## The asymmetry that governs this skill

`how` and `why` read what exists. They can come back empty, and an empty
result is informative.

This skill **generates**. It can always produce three plausible options, and
plausibility is free. Left ungated it manufactures evidence for
`principle-prove-it` — which is the exact failure that principle exists to
stop.

So every option carries a label and the label is load-bearing:

| Label | Means | Authority |
| --- | --- | --- |
| `considered` | Someone actually weighed this — cite the PR comment, commit, doc, or rejected design | Evidence |
| `invented` | Produced here, never tried | Hypothesis only |

An `invented` option may not decide anything until `spike-and-validate`
turns it into a run with real output. Saying "we considered X and rejected
it" about an option nobody ran is a false claim about the record.

## Step 1. Bound the decision

State in one line: what is being chosen, and what makes it expensive to
reverse. A decision that is cheap to reverse does not need this skill —
make it, and move on.

Pull **Avoid** from `why` if it ran. Options already tried and failed are
`considered` with a citation, not fresh ideas.

## Step 2. Fan out

2–4 subagents, spawned in **one message**, each given the same brief and a
different constraint to optimize for (fewest moving parts, easiest to
delete later, best for the caller, cheapest to migrate). Different
constraints, not different phrasings — same-brief subagents converge.

Each returns rows in the shape at
`corpus/skills/principle-prove-it/references/finding-shape.md`, with
`grounding` set to `invented` unless it can cite where the option was
already weighed.

Give each one its own worktree if it writes anything. Scope wording is not
filesystem isolation.

## Step 3. Merge into an option set

For each surviving option:

- **Shape** — what the caller writes, first. Then types and boundaries.
- **Label** — `considered` with citation, or `invented`.
- **Cost to reverse** — the real question behind most of these decisions.
- **What would kill it** — the check that would rule it out. This line is
  the spike brief.

Include the status quo as an option. It is `considered` by definition and
frequently wins.

## Step 4. Route

- All options `considered` → decide now, cite the record.
- The leading option is `invented` and expensive to reverse →
  `spike-and-validate` before committing.
- Subagents disagree on which constraint matters → that is the real
  decision. Surface it instead of picking quietly.

## Do not

- Pad the set. Two real options beat four where two are strawmen.
- Present an `invented` option as prior art.
- Run this on a reversible decision.
