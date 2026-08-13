---
name: draft-pr
description: >
  Draft or update a pull request using a disciplined PR schema (Summary,
  Review Claim, Review Lane, Review Unit, Safety Invariant, Slice Rationale,
  Non-goals, Test Plan, Revert Plan), a diff-atomicity gate, and visual-proof
  rules for UI-impacting changes. Trigger when asked to make a PR, draft or
  update a PR body, prepare PR text, or whenever a branch/PR change means the
  PR's title/body may now be stale.
---

# draft-pr

Use this skill when the work is already done and the user wants a PR created,
updated, rewritten, split, or republished, and whenever a branch or diff
change could leave a PR's title/body out of date with the actual code.

Apply `split-scope` (this bundle's companion skill) before writing titles or
PR bodies for a stack: if one branch mixes more than one local review claim,
split the stack first.

## Scope & Ambiguity Confirmation

Before drafting a PR body, resolve scope and ambiguity with the user in
conversation. Do not draft through unresolved ambiguity.

Ask a concise, concrete question — instead of drafting speculatively — when,
after looking at the actual diff/changed files:

- The review lane cannot be inferred with confidence: no single lane's
  compatible unit set covers the large majority of changed, non-neutral files.
- The changed files plausibly span more than one review unit under the
  active `drafter.config.json` taxonomy, and grouping them isn't covered by an
  explicit Boundary/Grouping rule (see `split-scope`'s Grouping Rules).
- The slice boundary is undecided: the diff could reasonably ship as one PR or
  a multi-PR stack, and each framing changes what a reviewer is being asked to
  approve.
- A configured pairing ban (see `drafter.config.json`) is half-triggered — one
  of its two paths changed, not the other.

If none of these hold, proceed and record the resolved choice under an
`Assumptions:` note rather than asking. Do not ask about a choice that has
exactly one non-arbitrary answer.

**Safety Invariant Confirmation is a standing rule, independent of the above:**
always propose the `## Safety Invariant` text and ask the user to confirm or
correct it before finalizing a PR body — even when scope was completely
unambiguous. Mechanical slices may use a terse invariant; confirmation is
still required. Nothing in this skill or its validator enforces that a human
actually answered — this is a conversational convention you must actually
follow, not a check you can skip because the tooling would let you.

**Headless / non-interactive mode:** when invoked under a directive that
forbids clarifying questions (a benchmark prompt, an explicit non-interactive
flag), skip all asking above, resolve every open point to your best-effort
default, and record each one under `Assumptions:` instead — including the
Safety Invariant, marked as unconfirmed in the output.

## Stack ordering

Order slices so a reviewer reads the evidence before the change it justifies:

- **Repro/proof comes before the fix.** Land the repro or regression proof as
  the earlier slice and the behavior fix as the later slice, so the bug is
  demonstrated before the change is approved.
- Foundation (types, helpers, migrations, flags) precedes behavior; cleanup
  and docs come last.

## Preferred PR schema

Default to this structure (validated by `validatePrBody()` in
`@neko-catpital-labs/drafter-core`):

```md
## Summary

Plain-English explanation of what changed and why. Paragraphs, not bullets,
under 30 words each (configurable via `drafter.config.json`'s
`prBody.summaryWordLimit`). One idea per paragraph.

## Review Claim

State the one thing the reviewer is being asked to approve.

## Review Lane

Choose exactly one from your `drafter.config.json` taxonomy (default:
`behavior`, `refactor`, `proof`, `cleanup`, `policy`, `docs`).

## Review Unit

Choose exactly one matching review unit from your configured taxonomy. The
unit must match the changed files — the validator rejects a declared unit
that ships files assigned to another unit.

## Safety Invariant

Explain why this slice is safe to review locally. Propose it and get the
user's confirmation before publishing (see Scope & Ambiguity Confirmation
above).

## Slice Rationale

Explain why this work is split here instead of bundled elsewhere.

## Non-goals

List what this slice explicitly does not change. For a `refactor` lane,
include one of: `no behavior change`, `behavior unchanged`, `unchanged
behavior`, or `pass unchanged`.

## Architecture

Only include this section when the change modifies component interactions,
control flow, state flow, or data flow. Quote Mermaid labels that contain
prose, punctuation, or code-ish text.

### Before

\`\`\`mermaid
graph TD
    A["old flow"]
\`\`\`

### After

\`\`\`mermaid
graph TD
    A["new flow"]
\`\`\`

## Test Plan

<details>
<summary>Test Plan</summary>

- [ ] exact command
- [ ] exact command

</details>

## Visual Proof

Required when the diff changes UI-impacting files. Include before/after
screenshots or a video link.

## Revert Plan

<details>
<summary>Revert Plan</summary>

- Safe to revert? Yes/No
- Revert command: `git revert <sha>` or equivalent
- Post-revert steps: None / concrete steps
- Data migration? No / concrete steps

</details>
```

If the change is small and has no architectural impact, omit `## Architecture`
rather than forcing filler.

Use visible markdown sections for review metadata. Do not hide `Review
Claim`, `Review Lane`, `Review Unit`, `Safety Invariant`, or `Slice Rationale`
inside `<details>` or other HTML disclosure blocks — they must render
directly in the PR body. Test Plan and Revert Plan are the opposite: keep
their headings visible, but their content must sit inside a collapsed
`<details>` block with `<summary>Test Plan</summary>` /
`<summary>Revert Plan</summary>`.

Do not default to a lightweight `## Summary / ## Testing / ## Notes` PR body.
Use the schema above as the floor.

## Visual proof rules

If the change is UI-impacting, capture before/after screenshots or a video
first. UI-impacting means the user-visible experience changes, even when no
file under a conventional UI directory changes.

- Visual proof must show the changed behavior itself, not just the changed
  screen area. Open every screenshot or video and verify the user-visible
  target is present and identifiable.
- If the changed behavior spans multiple states or a state transition —
  restart persistence, before/after transitions, progress animations, opening
  then dismissing overlays — use animated proof (gif/mp4/webm/walkthrough
  video). Static screenshots alone are not enough.
- When the claim is that a state persists across an action (navigation,
  restart, refresh, resize), each screenshot must also show the action
  happened, with an on-screen cue distinguishing each step.
- Caption each visual proof item with the concrete thing the reviewer should
  see.
- Before/after proof images must use distinct local filenames before upload
  (a shared upload prefix keyed by basename can otherwise collapse two
  different images into one URL).

## Diff atomicity gate

Run `lintDiffAtomicity()` (or the CLI at `scripts/lint-diff-atomicity.mjs`)
before publishing. Fatal findings — generated files mixed with hand-written
source, an orphaned lockfile change, a debugger statement, a focused
(`.only`) test — are hard failures; split the PR to clear them. Warnings
(readability findings like file count or unrelated-area spread) are
advisories — confirm the spread is intentional rather than silently ignoring
them.

If one branch mixes behavior, refactor, cleanup, or proof/test-harness work,
split the work into separate PRs. Do not relabel the lane or weaken the
checker to make a mixed branch pass.

## Command surface

The scripts below import `@neko-catpital-labs/drafter-core`. Install it once
in the repo you're drafting PRs for (`npm install --save-dev
@neko-catpital-labs/drafter-core`) so Node can resolve the import — a globally
installed skill copy can't resolve a bare import on its own.

1. Branch from your canonical base remote (see `references/branching-workflow.md`).
2. Push the working branch to your publish remote.
3. Start from the canonical template and validate it:

```bash
npx @neko-catpital-labs/drafter-mcp --help  # or call validate_pr_body via MCP
node scripts/validate-pr-body.mjs --body-file /tmp/my-pr.md --base main
```

4. Create or update the PR with your own repo's normal PR-creation flow (`gh
   pr create`, `gh pr edit`, or your platform's equivalent) once validation
   passes.

After any branch update, rebase, or force-push, refresh the PR title and body
so they still match the live diff. Re-check `## Summary`, test commands,
revert guidance, and any visual proof section; old copy is stale the moment
the branch meaning changes.

## Upstream-first workflow

Use the canonical repository as the PR target and an explicit publish remote
for branch publication. Create branches from `<baseRemote>/<base>`; open PRs
against the canonical repository's base branch. See
`references/branching-workflow.md`.

## Merge-queue tools (Mergify, etc.)

If this repo uses a merge-queue or stacked-PR tool, follow that tool's own
publish workflow after this skill produces a validated body/branch — that
integration is out of scope for this skill.

## Validation

- Ensure the PR title still matches the current slice after any branch update
  or force-push.
- Ensure the `## Summary` section still describes the current diff.
- Ensure the branch is pushed.
- Ensure body sections are present and concrete; test commands are real
  commands that were actually run when possible; revert guidance is honest.
- Keep Test Plan and Revert Plan content inside their collapsed `<details>`
  blocks.
- Do not create or update a PR when the branch has no file changes against
  its selected base, or contains an empty commit slice.
- For UI-impacting diffs, include `## Visual Proof` before publishing;
  classify by user-visible behavior, not by path alone.

## References

- `references/branching-workflow.md`
- `scripts/validate-pr-body.mjs`
- `scripts/lint-diff-atomicity.mjs`
- `scripts/pr-body-template.mjs`
