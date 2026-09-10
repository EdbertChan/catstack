# Skill triggers: what the model may fire on its own

Every skill in this repo is in one of two states, set by one line of
frontmatter.

**Auto-fire** (no flag). Claude Code loads the skill's `description:` and the
model may invoke the skill when a turn matches it. Use this for a gate or a
procedure that is worthless if it only runs when someone remembers to name
it — `principle-prove-it` fires on a claim taking shape, `narrow-the-scope`
on a loop that is not converging.

**Explicit only** (`disable-model-invocation: true`). The `description:` is
never loaded into context, so no description match can reach the skill. The
only way in is a typed `/<name>`. Use this for steering vocabulary you reach
for deliberately (the `principle-*` set), personal convention files
(`*-mode`), and anything whose blast radius demands a human in the loop.

## How to choose

Ask what happens when the model guesses wrong in each direction.

| | A false fire costs | A missed fire costs |
| --- | --- | --- |
| Gate / evidence rule | A little context | A wrong claim reaching the user |
| Steering vocabulary | Context on 25 principles every task | Nothing — you name it when you want it |
| Irreversible action | A force-merge nobody asked for | A human types six more words |

Auto-fire when a missed fire is the expensive direction. Flag it when a
false fire is.

## Prose is not a trigger mechanism

A skill cannot opt out of auto-invocation by asking. `admin-bypass-sweep`
force-merges PRs past required checks, and its description said "MANUAL,
HUMAN-ONLY ... Do not auto-invoke this skill from a natural-language
request, a description match, or another agent's delegation" — while
remaining fully auto-invocable, because the flag was missing. The model reads
that description to decide whether to fire; the sentence asking it not to is
inside the thing it is matching on.

`scripts/check_skill_trigger_policy.py` fails closed on that contradiction:
a skill that declares itself manual in its own frontmatter must carry the
flag. It also regenerates the inventory below, because a hand-maintained
list of 35+ skills is stale by the next PR.

```sh
python3 scripts/check_skill_trigger_policy.py          # verify
python3 scripts/check_skill_trigger_policy.py --write  # regenerate
```

Fixture contracts follow from the same line — see
`scripts/check_skill_trigger_mechanism.py`. A flagged skill's
`fires_*.md` must contain its literal `/<name>`; an auto-fire skill's must
instead share vocabulary with its `description:`.

## Inventory

<!-- BEGIN generated: skill-triggers (scripts/check_skill_trigger_policy.py) -->

### Auto-fire (21)

The model may invoke these from a description match. Everything here is a gate or a procedure that is useless if it only runs when named.

`create-skill`, `draft-pr`, `make-pr`, `thrash-reflect-automate`, `principle-flag-your-own-corrections`, `principle-prove-it`, `principle-subagent-inherits-scope`, `prove-it-ship-gate`, `alternatives-considered`, `diu`, `how`, `land-stack`, `loop-generator`, `narrow-the-scope`, `plan-first`, `ship-a-detector`, `show-me-your-work`, `spike-and-validate`, `split-scope`, `visual-proof`, `why`

### Explicit invocation only (32)

These carry `disable-model-invocation: true`. Claude Code does not load their `description:` at all, so the only way in is a typed `/<name>`.

`automate-me`, `reflect`, `cat-mode`, `principle-assert-invariants-not-last-bug`, `principle-bind-to-named-inventory`, `principle-build-the-lever`, `principle-encode-lessons-in-structure`, `principle-experience-first`, `principle-explicit-errors`, `principle-fix-root-causes`, `principle-foundational-thinking`, `principle-generalize-from-rejection`, `principle-guard-the-context-window`, `principle-laziness-protocol`, `principle-manage-idle-resumption`, `principle-minimize-reader-load`, `principle-name-the-scorer`, `principle-never-block-on-the-human`, `principle-no-lookahead`, `principle-outcome-oriented-execution`, `principle-push-not-poll`, `principle-report-the-disqualifier`, `principle-scope-the-session`, `principle-separate-before-serializing-shared-state`, `principle-sequence-verifiable-units`, `principle-subtract-before-you-add`, `principle-trace-token-burn-loop`, `principle-type-system-discipline`, `report-rendering`, `admin-bypass-sweep`, `i-have-adhd`, `independent-judge-swarm`

<!-- END generated: skill-triggers -->
