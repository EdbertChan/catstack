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

Do not mix `engine-runtime` with `corpus-lesson` in one PR unless Neutral files only. See [docs/ecosystem.md](../../docs/ecosystem.md).

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
python3 scripts/check_skills_three_harnesses.py
python3 scripts/check_ecosystem_boundaries.py
```

Must pass. A skill MUST install to Claude, Cursor, and Codex (unless listed
in `CLAUDE_ONLY_SKILLS`). Do not publish a skill that only documents a
single harness. Do not land a skill in the wrong bucket.

`hooks/auto-pr`'s delivered instruction already tells the agent to run these
checks as part of its auto-triggered flow; a human asking for a PR
interactively should run them too before publishing.
