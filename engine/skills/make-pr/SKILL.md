---
name: make-pr
description: >
  catstack-local overlay for the draft-pr skill: adds extra gates before
  publishing a PR that touches engine/hooks, engine|corpus|product skills --
  hook e2e coverage, three-harness install, and ecosystem boundaries.
  Loaded automatically instead of draft-pr for PRs in this repo.
---

# make-pr (catstack overlay)

Use `draft-pr`'s schema, confirmation rules, and diff-atomicity gate exactly
as documented -- this file only adds repo-local rules on top.

## Review unit from path

Declare exactly one review unit that matches the dominant changed paths:

| Paths | Review Unit |
| --- | --- |
| `engine/` (hooks, engine skills, scripts) | `engine-runtime` |
| `corpus/skills/` | `corpus-lesson` |
| `product/skills/` | `product-skill` |

One review unit per PR; neutral files (`docs/`, repo-root `tests/`) ride
along. See [docs/ecosystem.md](../../../docs/ecosystem.md). A change whose
code reads another unit's output is two stacked PRs, producer first -- not
one PR with the coupling explained in Slice Rationale.

## Stack on top, or overwrite the branch

A PR that already exists gets one of two treatments, decided from its current
diff against its base -- never from how much work went into it, and never by
asking the user which they would prefer:

- **Stack on top** when the claim still holds and what is being added is
  small: a fix to code the PR already ships, the base merged in, or docs for
  the same claim. Push another commit to the same branch, or open a new PR
  based on it.
- **Overwrite the branch** when the diff no longer matches the claim. Any one
  of these is enough:
  - it carries work already on the base
  - it mixes review units
  - it ships a second claim

  Save the old head as `backup/pr<number>-<short-sha>`, say where it went,
  then `git push --force-with-lease=<branch>:<old-sha>` and rewrite the title
  and body to the slice that remains.

The record that gets read later is the PR's final diff and body, so a branch
whose diff stopped matching its title is rewritten, not explained in Slice
Rationale. `--force-with-lease` and the backup branch are the floor, not a
precaution to skip: a lease failure means another session moved that branch,
so re-read it and decide again instead of forcing past it.

## Preflight (run first)

```sh
python3 engine/skills/make-pr/scripts/preflight.py --base origin/main
```

It reads the diff, prints the review unit from the table above, fails on any
mix of review units (printing one `split` line per unit), and runs every gate
below for the hooks and skills actually touched. Paste its output into the
PR's Test Plan. The sections below describe what it runs; you only run them
by hand if it fails.

A failing preflight or `validate-pr-body.mjs` is a stop, in headless and
merge-gate runs too: do not emit a publishable body that says "needs
splitting" or "not ready to merge". Output the `split` lines and the failing
check's message instead, so whatever publishes gets nothing to publish
(fail-safe defaults, Saltzer & Schroeder 1975,
https://web.mit.edu/Saltzer/www/publications/protection/Basic.html).

## Extra gate: hook e2e coverage

Before publishing any PR that touches `engine/hooks/<name>/`:

```sh
python3 scripts/check_hook_test_coverage.py engine/hooks/<name>
```

Must pass for every touched hook that has a `detect.py`. If it fails, add
the missing positive test (reproduces the bad case the hook exists to
catch, asserts it fires) or negative test (a clean case, asserts it stays
silent) first -- do not publish around the gate. This is in addition to,
not instead of, `draft-pr`'s own diff-atomicity gate.

## Extra gate: skills three-harness install

Before publishing any PR that adds or changes a skill under
`engine/skills/`, `corpus/skills/`, or `product/skills/`:

```sh
python3 scripts/check_skill_test_coverage.py --base <actual-pr-base> --head HEAD
python3 scripts/check_skills_three_harnesses.py
python3 scripts/check_ecosystem_boundaries.py
```

All must pass. The coverage command is diff-aware: each changed skill must
change its own colocated or explicitly mapped test in that direct PR slice;
tests inherited from a parent or child stack slice do not count. A skill MUST install to Claude, Cursor, and Codex (unless listed
in `CLAUDE_ONLY_SKILLS`). Do not publish a skill that only documents a
single harness. Do not land a skill in the wrong bucket.

`engine/hooks/auto-pr`'s delivered instruction already tells the agent to run these
checks as part of its auto-triggered flow; a human asking for a PR
interactively should run them too before publishing.

## Extra gate: fixture vs live on ship closeout

On stack/PR closeout for workers or integrations whose Goal includes live
side effects (Linear, deploy, live mine, external APIs):

- Require an explicit **fixture vs live** split in the Test Plan and Summary.
- Either include live evidence from the same turn, or prefix unsettled live
  claims with `UNVERIFIED: live path`.
- Visual Proof that only shows UI registration must not be framed as product
  e2e of the live side effect.

Follow `prove-it-ship-gate` and Invoker or locally installed `prove-it`.
