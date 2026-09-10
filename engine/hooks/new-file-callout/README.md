# new-file-callout

Stop hook: a new file at the repo root or under a top-level `scripts/` must
be named in the reply that leaves it there. At Stop the hook runs
`git status --porcelain --untracked-files=all` in the hook's `cwd`, keeps
the untracked entries at the root or under `scripts/`, and narrows to the
ones this turn touched: named in a Write / Edit path, a shell redirect or
`tee` / `cp` / `mv` / `touch` target, a tool result, a subagent
task-notification, or modified since the turn's first message. If the reply
does not contain each file's name, the turn is blocked (exit 2) with the
list.

A subagent can leave a new file at the repo root while the parent reply is
about something else entirely, so the file ships unannounced and its owner
first meets it days later with no idea what created it. Naming the file in
the reply is what makes an unwanted one cheap to reject on the spot.

Whether the stated reason is a good one stays with the model. Untracked
files that predate the turn and were not touched pass; nested files pass;
not inside a git repo, unreadable transcript, or `stop_hook_active` fail
open.

## Files

- `detect.py` -- turn context (paths, text, start time), git status filter,
  `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/fixtures/new_files_{fires,silent}.json` -- the real subagent case
  and its named form, a `scripts/` drop, a stale file, a nested file.
- `tests/test_hooks.py` -- each fixture runs against a throwaway git repo.

Tests: `python3 -m unittest discover -s engine/hooks/new-file-callout/tests -v`
