# Branching workflow

Upstream-first, origin-only branching policy:

1. Fetch the canonical base remote (`origin` in most setups).
2. Branch from `<baseRemote>/<base>` (for example `origin/main`).
3. Push the working branch to your publish remote (usually the same
   `origin`, or a fork remote if you don't have push access to the
   canonical repo).
4. Open the PR against the canonical repository's base branch.

Do not depend on fork-sync scripts before PR creation — always branch fresh
from the canonical base ref so the diff is computed against current `main`,
not a stale local copy.

If your repo uses a stacked-PR tool (Mergify Stacks, Graphite, git-branchless,
etc.), follow that tool's own branch-naming and publish conventions on top of
this policy — `draft-pr` only owns the PR body/schema, not stack mechanics.
