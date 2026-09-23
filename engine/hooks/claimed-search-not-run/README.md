# claimed-search-not-run

Stop hook: the outgoing message cites a history search as having run, and no
Bash call in the session matches it. Advisory — stderr plus exit 0.

## The gap it closes

Three existing gates read the outgoing message for evidence, and all three
pass the turn this hook exists to catch:

- `hedge-runs-prove-it` fires on a hedge next to **no** verification tool.
  The turn below ran 24 real commands, so it passes.
- `prove-it-ship-gate` fires on done/shipped claims about a **live surface**.
  A class-search result is neither, so it passes.
- `history-before-reversal` already knows that `git log --grep` searches
  commit messages while `-S`/`-G`/`-L`/`--follow`/`git blame` search the
  history of the code — but it only guards `git revert`.

The uncovered shape is the confident, specific, false citation: a command
named in the summary that was never run. Here the trigger is the **claim**,
not the act.

## The shape it was built from

A CI-repair worker closes with a line of this form:

> Class-search (`git log --all --grep`/`-S`, `gh pr list`) turned up no prior
> fix of this class needing generalization.

Its transcript carries the commit-message grep and the PR search. It carries
no `git log -S`. A repo whose contributing rules require both forms before a
root cause is stated as settled now has a summary that reads as if both ran,
and a reader has no way to tell which half happened. The cheap half of the
pair is the one that survives, because it is the one that is easy to type.

## Fires on

A sentence that satisfies all of:

1. Contains a **backticked** span naming `git log`, `git blame`, `gh pr list`,
   or `gh search`, carrying one of `-S`, `-G`, `-L`, `--follow`, `--grep`,
   `--search`. A flag-only span (`` `-S` ``) attaches to the nearest preceding
   base command, because `` `git log --all --grep`/`-S` `` is how the
   shorthand is actually written.
2. Reads as a **report**: ran, searched, class-search, turned up, returned,
   found, no hits, nothing, confirmed, clean, empty …
3. Reads as **not** an instruction: should, must, need to, next time, todo,
   consider, try, recommend, before finalizing, the fix is …

and whose cited `base + flag` appears in no `tool_use` Bash command in the
transcript.

## Silent on

- The cited search actually ran (`code_history.jsonl`).
- A command proposed rather than reported — "next time we should run
  `git log -S <token>`".
- An un-backticked mention, so prose never matches.
- `gh pr list --search` read as `git log -S`; the flag match is case-sensitive.
- No transcript path, an unreadable transcript, or a transcript with no Bash
  calls at all — fail-open, since an unread file is not evidence of absence.
- `stop_hook_active`, or enforcement not switched on.

## What it deliberately does not claim

That a search which *did* run was conclusive. In a shallow clone —
`git rev-parse --is-shallow-repository` → `true`, which is the normal state of
a disposable repair worktree — `git log --all` cannot see past the graft
boundary and `git merge-base --is-ancestor` reports NOT-ancestor for plainly
merged commits. This hook only checks that the cited command ran. Whether its
negative result means anything is a separate problem, and a larger one.

## Tests

```
python3 engine/hooks/claimed-search-not-run/tests/test_hooks.py
```
