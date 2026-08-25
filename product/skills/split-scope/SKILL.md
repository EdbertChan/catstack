---
name: split-scope
description: >
  Shape code changes and PR stacks so each diff is easy to review: one local
  claim, one safety invariant, clear architectural effect, and an explicit
  reason for the slice. Trigger before authoring implementation work, PR
  stacks, or any multi-diff plan, or when asked to split/scope/compress a
  change into reviewable pieces.
---

# split-scope

Use this skill before authoring implementation work, PR stacks, or any
multi-diff plan. Optimize for reviewer cognition, not smallest total patch.

## Core Rule

Each diff or workflow should make one locally reviewable claim. A tired senior
engineer should be able to answer:

- What architectural thing changed?
- Why does this slice exist?
- Why is it safe?
- What alternatives were rejected?

## Required Metadata

Every implementation slice should carry these fields in task descriptions and
PR bodies:

- `Review claim:` one sentence the reviewer is being asked to approve.
- `Review lane:` exactly one lane from your `drafter.config.json` taxonomy
  (default: `behavior`, `refactor`, `proof`, `cleanup`, `policy`, or `docs`).
- `Safety invariant:` why this slice is safe to review locally.
- `Slice rationale:` why this work is split here instead of bundled elsewhere.
- `Architectural effect:` what changed in control flow, data flow, ownership,
  dependency direction, or public surface.
- `Alternative considerations:` rejected designs or split shapes.
- `Non-goals:` what this slice explicitly does not change. When stacking
  slices, a Non-goal that says "leave shared policy X alone" / "do not change
  doctor policy" means this slice inherits the prior magic number — it is not
  independent evidence that X was re-validated. If you need to change X, put
  that in its own claim; do not treat sibling Non-goals as a re-vote.

For mechanical slices, these can be terse. For cross-boundary changes, explain
the before/after architecture and why the split is acceptable. Each slice must
still contain one conceptual unit; a validator (`classifyReviewScope()` in
`@neko-catpital-labs/drafter-core`) can infer mixed units from the claim,
rationale, implementation details, and change-type entries when you configure
`drafter.config.json`'s text-pattern rules.

## Safety Invariant Confirmation

Before finalizing an implementation plan or PR stack, propose the `Safety
invariant:` for every slice and ask the user to confirm or correct it. Keep
the existing heading and definition: it explains why the slice is safe to
review locally. Mechanical slices may use terse invariants, but they still
require user confirmation.

This is a pure conversational convention — no code in this toolkit enforces
that a human actually answered. Follow it because it's the right discipline,
not because a validator will catch you skipping it.

## Ordering Rules

- Evidence before change: add repros, benchmarks, or instrumentation before the
  fix when they prove the problem.
- Refactor before behavior when the extraction is reusable and behavior-neutral.
- Foundation before behavior: add schemas, types, helpers, migrations, flags,
  and dormant code before behavior changes.
- Compatibility before exposure: include adapters with a lower-level change
  when needed to preserve existing behavior.
- Behavior before cleanup: fix correctness or security first; rename and cleanup
  later.
- Activate one surface or path per diff.
- Delete after migration, in a separate deletion slice as soon as safely unused.
  Exception: a pure rehome/relocation of an already-cohesive unit (no
  decomposition) deletes the old path in the SAME slice as the move — see
  `playbooks/rehome-relocation.md`.

## Boundary Rules

Split across architectural boundaries unless the downstream edit is required to
preserve existing behavior.

Common boundaries:

- DB migration, write path, read/API exposure, UI use, old column deletion.
- Core behavior, API exposure, UI behavior.
- Contract, handler, UI.
- CLI, API, UI.
- Mechanical rename, module reorganization.
- Helper extraction, usage migrations.

Exception: directly affected tests and compatibility adapters stay with the
change that requires them. Unrelated test stabilization and optional cleanup are
separate slices.

## Grouping Rules

Group changes only when they share the same review claim:

- generated output with the source schema change
- docs explaining the changed behavior, API, or default
- visual proof with the UI behavior change
- dependency bump with required adaptation
- exact same mechanical migration across many files
- pure repo-wide import-path rename

Split changes when they introduce a different claim:

- optional cleanup
- special cases inside a mechanical migration
- stale unrelated screenshots
- behavior fix plus rename
- default flip plus dead-path removal
- refactor/extraction plus new fields or other behavior changes
- benchmark/repro/proof harness plus the fix it is meant to justify
- product code plus planning/policy/docs updates
- broad mechanical moves too large to inspect comfortably
- multiple distinct extractions from one file (one top-level symbol move per slice)

## Refactor playbooks

Two detailed, Fowler/Tidy-First-grounded sequencing playbooks live alongside
this file — read the one that applies before sequencing a refactor-lane stack:

- `playbooks/decomposition-extraction.md` — splitting one file's symbols
  across multiple NEW modules (one top-level symbol per PR).
- `playbooks/rehome-relocation.md` — moving an already-cohesive unit (a whole
  file or package) to a new location with content materially unchanged.

Both playbooks end with `## Naming the Technique`'s rule (see
`references/technique-catalog.md`): every `refactor`-lane PR names its single
Fowler/refactoring.guru technique in the form `<Technique>: <what moved>`.

## PR Body Guidance

Do not summarize the patch file-by-file. Compress the human judgment:

- state the review claim
- state the safety invariant
- describe architectural effect in plain English
- call out why this slice exists
- include alternatives for non-obvious or cross-boundary choices

## Checking your Review Unit against a rehome's old path

If a `drafter.config.json` path rule classifies paths by directory convention
(for example `scripts/**` as `tooling-policy`), and your validator rejects a
PR whose changed files span more than the declared Review Unit: when rehoming
a file whose old path has a classification, declare the Review Unit that
matches the OLD path unless the new path is independently classified the
same way — check `classifyReviewUnitsForPath()` for both paths before
authoring the PR body.
