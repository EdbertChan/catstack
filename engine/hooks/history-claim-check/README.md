# history-claim-check

Blocks a PR publication whose body states a claim about the repo's own history
with no evidence beside it.

Durations, counts, authorship and never/always statements about code are the
cheapest facts in the repository to check — one `git log` each — and the easiest
to feel certain about without checking. That combination is what puts them into
a PR body, where they read as measured and outlive the session that wrote them.

## What it catches

| Shape | Example that shipped | The command |
| --- | --- | --- |
| duration | "stale for roughly five months" | `git log -S '<string>' --format='%ad %h' --date=short` |
| count | "three reflect passes found this" | `git log --grep=... \| wc -l` |
| authorship | "written by an agent" | `git log --format='%an <%ae>' -- <path> \| sort -u` |
| never/always | "never loaded on that machine" | `git log --all -S '<token>' -- <path>` |
| first/last | "first broken at <sha>" | `git log --all -S '<token>' --reverse` |

All five rows are drawn from one PR body. The first three were wrong: the window
was 24 days, one pass found it, and a human wrote the file.

## What clears it

Evidence within six lines of the claim — a fenced block, a named `git log` /
`git blame` / `git show`, a commit sha, or an explicit `UNVERIFIED:`. The point
is not to forbid the claim but to make the query cheaper than the guess.

## Scope

Fires only on commands that write a PR title or body to GitHub: `gh pr
create`/`edit`, `gh api ... /pulls`, and `create-pr.mjs`. Reads `--body`,
`--title`, `--body-file`, `--input` and inline heredocs. Everything else passes
untouched — a commit message mentioning "five months" is not blocked, because a
commit is revisable in a way a published PR body is not.

## Tests

`python3 -m pytest engine/hooks/history-claim-check/tests` — three fixtures that
must fire, five that must stay silent.
