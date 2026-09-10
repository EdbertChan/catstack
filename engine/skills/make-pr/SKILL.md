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

Do not mix `engine-runtime` with `corpus-lesson` in one PR unless Neutral files only. See [docs/ecosystem.md](../../../docs/ecosystem.md).

## Preflight (run first)

```sh
python3 engine/skills/make-pr/scripts/preflight.py --base origin/main
```

It reads the diff, prints the review unit from the table above, fails on an
engine-runtime + corpus-lesson mix, and runs every gate below for the hooks
and skills actually touched. Paste its output into the PR's Test Plan. The
sections below describe what it runs; you only run them by hand if it fails.

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

## Extra body section: Backtest

A PR that changes a detector pattern -- a regex, a pattern list, or a
threshold constant in `engine/hooks/*/` or `scripts/check_*.py` -- adds a
`## Backtest` section after `## Non-goals`. Fill it from a real
`scripts/backtest_detector.py --compare <base>` run, one key-value line per
field:

```md
## Backtest

- Command: python3 scripts/backtest_detector.py --detector engine/hooks/<name>/detect.py:<callable> --compare origin/main
- Messages scanned: 1843
- Hits before: 12
- Hits after: 15
- Newly caught: 4
- Newly missed: 1
- False positives accepted: 1
```

`False positives accepted` is how many of the hits after you read and judged
wrong but acceptable. Every value is a whole number, and hits after minus
hits before must equal newly caught minus newly missed. For a brand-new
detector there is no baseline: run without `--compare`, write 0 for hits
before and newly missed, and newly caught equals hits after.

Then run the gate against the body file:

```sh
python3 scripts/check_detector_backtested.py --base <actual-pr-base> --body-file /tmp/pr.md
```

Exit 0 is PASS, 1 is FAIL (a pattern changed and the block is missing or
wrong), 2 is UNCHECKED (the base ref, the diff, or the body could not be
read). UNCHECKED is not a pass: fetch the base or fix the path and rerun.

## Extra gate: fixture vs live on ship closeout

On stack/PR closeout for workers or integrations whose Goal includes live
side effects (Linear, deploy, live mine, external APIs):

- Require an explicit **fixture vs live** split in the Test Plan and Summary.
- Either include live evidence from the same turn, or prefix unsettled live
  claims with `UNVERIFIED: live path`.
- Visual Proof that only shows UI registration must not be framed as product
  e2e of the live side effect.

Follow `prove-it-ship-gate` and Invoker or locally installed `prove-it`.
