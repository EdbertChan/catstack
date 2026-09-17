The user asks for a plan to loosen a validation rule that rejects some
saved rows, across a schema file, a migration, and two test files.

This skill fires, and Step 0 runs first: `git log --oneline -15` on the
schema file, `gh pr view` on the PRs that shaped the rule, and
`git log -S` on the rule's error text to find the PR that added it. The
plan's `History:` line names those PRs and the decision each made, and
because the plan loosens a guard, the `why` skill's reversal steps run
before any slice is written.
