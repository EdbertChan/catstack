# history-before-reversal

Claude `PreToolUse` hook on `Bash`. Undoing merged work throws away the
reason the work was done, so this blocks a reversal until the session has
looked at that reason and at the history of whatever the change collided
with. It is the mechanical half of the `why` skill's "before you reverse"
step.

## Fires on

A shell command containing, in any `&&` / `;` / `|` segment:

- `git revert <commit>...`, including `git -C <dir> revert`, leading
  `VAR=value` assignments, and flags such as `--no-commit`, `--no-edit`, `-m 1`.
- `git commit -m "Revert \"...\""` (also `--message=`), the hand-written form
  of the same reversal.

It blocks when earlier shell commands in the same transcript lack either:

1. **A read of the change being reversed.** `git show <sha>` whose SHA
   prefix-matches a revert target, or any `gh pr view`, `gh api graphql`, or
   `gh api .../pulls/...` / `.../commits/...`. A hand-written revert commit
   names no SHA, so any `git show <sha>` or PR read counts.
2. **A search of code history.** `git log -S`, `git log -G`, `git log -L`,
   `git log --follow`, or `git blame`. `git log --grep` does not count: it
   searches commit messages, not the history of the code that conflicts.

Evidence is read from the whole session: the main log
`<dir>/<session>.jsonl` and every helper-agent log under
`<dir>/<session>/subagents/*.jsonl`. History research delegated to a helper
agent, as the `why` skill does, counts. A revert run by a helper agent sees
the main session's research too. The command being checked is excluded from
its own evidence.

## Silent on

- `git revert --abort | --continue | --quit | --skip`
- `git log --grep=revert`, `rg 'git revert'`, `echo 'git revert ...'`
- a commit message that mentions revert without starting with `Revert "`
- `git reset`, `gh pr view`, and heredoc bodies that contain `git revert`
- any non-shell tool, such as `Write` or `Edit`

## Block message

```text
history-before-reversal: this undoes merged work, and this session has not yet:
  1. read the change you are reversing: `git show <sha>` (its message carries the PR body) or `gh pr view <number>`
  2. search the history of the code that conflicts with it: `git log -S <token>` / `git log -G <regex>` on the guard, check, or test that is failing, or `git blame` / `git log --follow` on its file, then read the PR that added it
A reversal throws away the reason the change was made. Find out whether the thing it conflicts with is the real bug before undoing it, and say which PR you are reversing and why. See the `why` skill.
```

Only the missing steps are listed.

## Fail direction

Fails **open**, loudly. A payload that is not JSON, a payload with no
`transcript_path`, a transcript that is missing, over 64 MB, or has no
parseable line, and any detector exception all allow the command and print
`history-before-reversal: UNCHECKED, ...` to stderr. A helper-agent log that
cannot be read only adds no evidence; it does not make the verdict
UNCHECKED, because the main log was read. A reversal is
recoverable, and a broken hook must not stop unrelated git work.

## Escape hatch

None. Running the two reads is the way through; both are cheap.

## Non-goals

- A reversal done by hand-editing files back is not detected; the `why`
  skill covers it in prose.
- The hook does not judge whether the history search looked at the right
  code. It only proves one ran.
- Claude only. Cursor and Codex are not wired.
