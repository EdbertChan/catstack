---
name: how
description: >-
  Trace how a subsystem actually works before changing it. Use for "how does
  X work", a walkthrough before an edit, or placement questions ("where
  should this live", "which package owns this"). Fans out read-only
  explorers for a subsystem, one explainer for a narrow question. Use `why`
  for motivation, `alternatives-considered` for options.
---

# How

Build a working mental model of code you are about to change. The output is
the mechanism, not annotated source.

Feeds `principle-prove-it`: you cannot exercise the real artifact until you
know which artifact is real.

## Step 1. Size the question

State your reading of the scope in one line, then proceed. The user can
redirect.

- **Narrow** — one module, one function, one file. No fan-out. Read and
  explain in a single pass. Go to Step 3.
- **Broad** — a subsystem across files or packages, a cross-cutting flow, an
  architectural overview. Fan out first. Go to Step 2.

When it is ambiguous, take the narrow path. A second pass is cheaper than
four subagents answering a question that had one file in it.

## Step 2. Fan out (broad only)

Split the question into 2–4 angles that do not overlap. Spawn all explorers
in **one message** so they run concurrently:

- `subagent_type: Explore` (or `general-purpose` where Explore is absent)
- read-only; no edits, no worktree needed

Each explorer owns one angle and returns rows in the shape at
`corpus/skills/principle-prove-it/references/finding-shape.md`.

**Prompt hygiene:** give each explorer the question and the entry points,
not your working theory. A primed explorer finds roughly what you already
suspected.

**Every explorer states grounding per row.** `read-confirmed` means it
opened the actual import or call site and traced it. `name-matched` means
the path looked right. Two files can hold the same symbol name; a subagent
reasoning by name-proximity hands back a confident wrong file.

## Step 3. Explain

Merge the rows and write the explanation yourself. Sections, dropping any
that do not apply:

- **Overview** — what this does, in two sentences.
- **Runtime flow** — the actual call path, entry point to effect.
- **Key types** — the data structures the logic is written against.
- **Where things live** — `file:line` per claim, with the ref.
- **Gotchas** — the non-obvious parts, and what looks wrong but isn't.
- **Not traced** — every angle that came back empty or was not covered.

Do not drop the last section for brevity. A gap you name is a gap the reader
can fill; a gap you omit reads as coverage.

## Hand-off

When `how` precedes a change, end with the mechanism that must still work
afterward, phrased as a command or check. That line is what
`principle-prove-it` will demand output from later.

## Do not

- Explain from a grep hit. A name match is not a read.
- Fan out on a question one file answers.
- Report a flow you inferred from function names as if you traced it.
