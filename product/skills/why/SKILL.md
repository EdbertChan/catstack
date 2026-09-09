---
name: why
description: >-
  Recover why code is shaped the way it is before changing it. Use for "why
  does X work this way", "why was this threshold picked", design rationale,
  and dead-code questions. Anchors in git history and PR bodies first, then
  fans out one investigator per available evidence source and reports every
  null. Use `how` for runtime behavior.
---

# Why

`how` answers what the code does. `why` answers what forces produced it.

Feeds `principle-prove-it`: a constraint you cannot see is a constraint you
will delete. Most "we changed it back a week later" bugs are this.

## Operating posture

Careful and explicit about the line between what the record says and what
you are inferring from it. Never smooth an inference into a fact because it
reads better.

## Step 1. Anchor in the code

Build this inline **before** spawning anything. Every investigator starts
from it, so a weak anchor wastes the whole fan-out.

```sh
git blame -L <start>,<end> -- <file>          # last-touch commits
git log --oneline -20 -- <file>               # recent commits, PR numbers visible
git log --follow -p -- <file>                 # full history through renames
gh pr view <number> --json title,body,author,mergedAt,comments,reviews
```

Capture: file paths, line ranges, key symbols, commit SHAs, PR numbers, and
any ticket IDs those PR bodies reference. Read the PR bodies yourself. Review
discussion is where implementation-time rationale actually lives, and it is
usually the answer.

## Step 2. Fan out over the sources that exist

List the evidence sources actually available in this environment before
assigning any. Typical set: git and `gh` (always), the issue tracker,
long-form docs, team chat, error tracking, observability, analytics —
whichever have a working MCP or CLI here.

One investigator per source, spawned in **one message**. Do not hand one
subagent two sources; it will search the easy one and summarize the other.

Each returns rows in the shape at
`corpus/skills/principle-prove-it/references/finding-shape.md`.

**Document the null.** A source that returned nothing gets a row with
`null_result` set and a line in Sources Consulted. Skipping a source needs a
written reason in the output — "no MCP available here" or "provably
irrelevant, this is a build-time script with no runtime path." "Probably
irrelevant" is not a reason.

This is the same rule as the projection rule in `engine/CLAUDE.core.md`:
absence from a projection is not proof of absent state.

## Step 3. Report with the confidence separated

- **The question** — restated, and the code it points at.
- **What the record says** — cited. Commit, PR, ticket, message, with the ref.
- **What we can reasonably infer** — clearly marked as inference.
- **Competing explanations** — when two readings both fit, give both.
- **What we don't know** — including every null and every skipped source.
- **Sources consulted** — one line each, including the empty ones.

"Nobody wrote it down" is a real answer and often the most useful one: it
means the constraint is unprotected and the next person will break it too.

## Step 4. Convert to constraints (when a change follows)

If the `why` precedes an edit, end with:

- **Preserve** — behavior the history says was paid for.
- **Change** — what the original reason no longer justifies.
- **Avoid** — approaches the record shows were already tried and failed.
- **Risk** — what breaks if the recovered reason is wrong.

Hand that set to the plan. `alternatives-considered` treats **Avoid** as
already-explored ground.

## Do not

- Treat the most recent commit as authoritative. The current shape is
  usually accretion, not a decision.
- Report a PR body's claim as a fact about today's code without checking the
  code still matches it.
- Answer inline from one commit unless you can say why every other available
  source would have been redundant.
