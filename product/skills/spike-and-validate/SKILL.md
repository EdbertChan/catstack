---
name: spike-and-validate
description: >-
  Turn an untested assumption into real output by building the smallest
  throwaway that would kill it, running it, then discarding the code and
  keeping the finding. Use before committing to an invented option, an
  unfamiliar library or API, or a performance assumption. The gate on
  `alternatives-considered`.
---

# Spike and validate

A spike is an experiment, not a draft of the real change. Its only product
is a run with real output. The code goes in the bin.

This is the gate that makes `alternatives-considered` safe: an option nobody
ran is a hypothesis, and a spike is the cheapest way to stop it from
becoming a decision.

## Step 1. Write the kill condition first

Before any code, in one line: **what result would rule this out?**

If you cannot write that line, you are not spiking, you are starting the
implementation. Stop and say so.

The kill condition is falsifiable and specific. "See if the library works"
is not one. "Parses our 40MB fixture in under 2s on this machine" is.

## Step 2. Build the smallest thing that could fail

- Own worktree or scratch directory. Never the live checkout.
- Hardcode everything not under test. Config, auth, error handling, and
  edge cases are not what you are learning.
- No tests, no cleanup, no comments. This code is not going to review.
- Timebox it and say the box out loud. A spike that outgrows its box has
  become the implementation without anyone deciding that.

## Step 3. Run it and paste the output

The whole point. Real command, real output, in the same message as the
verdict — `principle-prove-it`, applied to your own experiment.

A spike that only passes proves less than you think. Where the assumption
has a failing side, show both: the case that works and the case that
breaks. A run that could not fail did not test anything.

## Step 4. Discard the code, keep the finding

**Delete the spike.** A spike promoted to production carries every shortcut
in Step 2 with it, and nobody remembers which lines were deliberate.

What survives is one row in the shape at
`corpus/skills/principle-prove-it/references/finding-shape.md`:

- `claim` — the assumption, now resolved.
- `grounding` — `read-confirmed`, because you ran it.
- `evidence` — the command and its real output.
- `null_result` — what the spike did **not** cover. Always fill this in. A
  spike proves one thing on one machine with one fixture.

Then say plainly: **validated**, **killed**, or **inconclusive**.
Inconclusive is a real outcome and much better than a spike quietly
reported as a pass.

## When not to spike

- The answer is in the code — that is `how`.
- The answer is in the history — that is `why`.
- The decision is cheap to reverse. Build it and change it later.
- You already know the answer and want cover for it. That is not an
  experiment.

## Do not

- Spike in the live checkout.
- Skip the kill condition and decide after the fact what the run showed.
- Ship the spike. If it turns out to be the right shape, rebuild it with
  the shortcuts removed.
- Report a spike that never ran as evidence for anything.
