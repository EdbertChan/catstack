---
name: principle-prove-it
description: "Apply before any claim about code, systems, or history. No claim without same-turn evidence; a hedge is a trigger to verify, never a place to stop. Routes the four investigation products that build the evidence. Unlike the other principles this one auto-fires: it must intercept a claim as it forms, not be named after the fact."
---

# Prove It

A claim is settled only when the evidence for it is in the same message.
Everything else is a hypothesis and must say so.

**Why:** the cheap signal always stands in for the expensive one. A build
passes and gets reported as "it works." A file exists and gets reported as
"it's wired up." A name matches and gets reported as "that's the bug." Each
substitution is individually reasonable and collectively how wrong answers
reach the user with confidence attached.

## The gate

Before writing any claim of the form "this is fixed," "this works," "the
cause is X," "it's merged," "N are running" — you must already have, in the
same message, one of:

1. A command run this turn, with its real pasted output. Not summarized.
2. A `file:line` read this turn, named with the ref it was read at.
3. A test name plus its real pass/fail line from the runner.

Otherwise write `UNVERIFIED:` immediately before the claim. There is no
softer wording. The full evidence rules live in `engine/CLAUDE.core.md` and
are always loaded; this file is the judgment half plus the routing below.

**A hedge is a trigger.** "I think," "probably," "should work" mean run the
check now, not lower the confidence and continue.

**Absence of output is not proof of success.** A command that printed
nothing needs its exit code shown.

## What builds the evidence

The gate says what counts. It does not gather anything. Four product skills
do that, each fanning out to parallel subagents and returning the shape in
`corpus/skills/principle-prove-it/references/finding-shape.md`:

| Product | Question | Returns |
| --- | --- | --- |
| `how` | How does this work now? | The mechanism you must exercise |
| `why` | Why is it shaped this way? | The constraint you must not break |
| `alternatives-considered` | What else could this be? | Options, each labeled considered or invented |
| `spike-and-validate` | Does the invented one hold? | A throwaway that ran, and its real output |

They compose in that order and each is optional. A one-line fix needs none
of them. A claim about a subsystem nobody on the team has read needs `how`
before anything else.

The pairing that matters: `alternatives-considered` **generates**, so it can
always produce three plausible options and none of them are evidence.
`spike-and-validate` is its gate. An invented option that reaches a decision
without a spike is exactly the manufactured evidence this principle exists
to stop.

## Related

- `prove-it-ship-gate` — the done/shipped auto-route for live side effects.
- `principle-fix-root-causes` — reproduce before explaining.
- `principle-sequence-verifiable-units` — end each unit in a check.
- Mechanical enforcement: `engine/hooks/prove-it-ship-gate`,
  `engine/hooks/hedge-runs-prove-it`, `engine/hooks/diu-stop`.
