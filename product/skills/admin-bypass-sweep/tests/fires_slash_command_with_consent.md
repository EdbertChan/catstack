User says: "/admin-bypass-sweep — I understand this bypasses CI and
force-merges to master. The queue's been stuck for an hour on a flaky
runner and there are six admin-bypass PRs waiting."

This is a literal, explicit slash-command invocation in the current
message, and it contains the exact required consent sentence verbatim. The
skill applies: discover and group the labeled PRs (Step 1), confirm scope
(Step 2), verify merge method (Step 3), then merge bottom-up with
`gh pr merge --admin` (Step 4) — never guessing at real conflicts (Step 5)
and proving final state before reporting (Step 6).
