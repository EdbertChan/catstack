---
name: make-pr
description: >
  catstack-local overlay for the draft-pr skill: adds extra gates before
  publishing a PR that touches hooks/<name>/ or skills/<name>/ -- hook e2e
  coverage and three-harness skill install. Loaded automatically instead of
  draft-pr for PRs in this repo, per draft-pr's own override rule.
---

# make-pr (catstack overlay)

Use `draft-pr`'s schema, confirmation rules, and diff-atomicity gate exactly
as documented -- this file only adds repo-local rules on top.

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

## Extra gate: skills three-harness install

Before publishing any PR that adds or changes `skills/<name>/`:

```sh
python3 scripts/check_skills_three_harnesses.py
```

Must pass. A skill MUST install to Claude, Cursor, and Codex (unless listed
in `CLAUDE_ONLY_SKILLS`). Do not publish a skill that only documents a
single harness.

`hooks/auto-pr`'s delivered instruction already tells the agent to run these
checks as part of its auto-triggered flow; a human asking for a PR
interactively should run them too before publishing.
