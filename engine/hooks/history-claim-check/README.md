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
`--title`, `--body-file`, `--input` (also in `--flag=value` form) and inline
heredocs. Everything else passes untouched — a commit message mentioning "five
months" is not blocked, because a commit is revisable in a way a published PR
body is not.

The publish words count only where the shell actually runs them: as the program
of a command, after `&&`, `;`, `|`, a newline, `if`, `VAR=x`, a wrapper such as
`env` or `sudo`, inside `$( )` or backticks, or in the script of `bash -c`. The
same words inside a quoted argument, a comment or a heredoc body are text, not a
publish — `git commit -m 'fix gh pr create'` is not checked. A line the parser
cannot read (an unclosed quote) falls back to the old plain-text match, so it is
treated as a publish rather than passed as clean.

## Write and publish in one command is refused

The hook runs before the command. If one command both writes the body file and
publishes it, the hook can only read the file as it is now — an older file,
maybe another session's — not the body the command is about to write. So when
a `--body-file` / `-F` / `--input` path is also written in the same command, by
a `>`/`>>`/`&>` redirect, a heredoc into `cat > file`, or `tee file`, the hook
refuses and asks for two commands: write first, then publish. Paths match by
file name, so a `cd` between the write and the publish cannot hide it.

A body file written in an earlier command is read and checked as before.
`--body-file -` (the body comes from stdin) is not a file write; its heredoc is
checked as inline text. Writers other than redirects and `tee` (`cp`, `mv`, a
script) are not recognized.

## Tests

`python3 -m unittest discover -s engine/hooks/history-claim-check/tests`.
