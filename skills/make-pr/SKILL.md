---
name: make-pr
description: >
  catstack-local overlay for the draft-pr skill: adds one extra requirement
  before publishing a PR that touches hooks/<name>/ or skills/<name>/ --
  the hook's e2e test coverage gate must pass. Loaded automatically instead
  of draft-pr for PRs in this repo, per draft-pr's own override rule.
---

# make-pr (catstack overlay)

Use `draft-pr`'s schema, confirmation rules, and diff-atomicity gate exactly
as documented -- this file only adds one repo-local rule on top.

## Extra gate: hook e2e coverage

Before publishing any PR that touches `hooks/<name>/` or `skills/<name>/`:

```sh
python3 scripts/check_hook_test_coverage.py hooks/<name>
```

Must pass for every touched hook that has a `detect.py`. If it fails, add
the missing positive test (reproduces the bad case the hook exists to
catch, asserts it fires) or negative test (a clean case, asserts it stays
silent) first -- do not publish around the gate. This is in addition to,
not instead of, `draft-pr`'s own diff-atomicity gate.

`hooks/auto-pr`'s delivered instruction already tells the agent to run this
check as part of its auto-triggered flow; a human asking for a PR
interactively should run it too before publishing.
