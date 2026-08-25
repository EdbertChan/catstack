# auto-pr

When catstack's own `hooks/`, `skills/`, `install.sh`, `CLAUDE.md`,
`CONTRIBUTING.md`, `cursor/`, `commands/`, `always-on/`, `docs/`, or
`.github/workflows/` change (uncommitted, or committed but not yet pushed),
tell the agent to open a PR for it -- no manual "make a PR" request needed.

Only ever fires inside the real catstack checkout: `repo_root()` resolves
this file's own location through `install.sh`'s symlink (via `realpath`,
not `abspath`) and requires the session's `git rev-parse --show-toplevel`
to match it exactly. A consumer repo that happens to have this hook
installed globally never triggers it.

The hook only detects and signals -- it never runs `git commit`/`push`/`gh
pr create` itself (see `detect.py`'s module docstring and
`tests/test_hooks.py::test_detect_source_has_no_git_write_verbs`). Delivery
hands the agent an instruction to run the `draft-pr` flow in its documented
headless mode: skip confirmation prompts, verify/add a positive+negative
test pair for any touched hook via
`scripts/check_hook_test_coverage.py`, then push and open the PR.

Claude has no true end-of-session hook, only `Stop` (fires every turn,
including mid-edit). Firing there immediately would mean opening a PR on
half-written code almost every turn. So Claude's `Stop` debounces: hash the
relevant diff every call; deliver only once the hash is unchanged from the
previous call (first stable/idle point), not on every single turn.

Cursor has a real `sessionEnd` event, so it needs no debounce: `stop`
(mid-turn) always stays silent, `sessionEnd` delivers once per diff hash.

Delivery is once-per-diff-hash either way (a `.prompted` marker), so a
truly unchanged diff never re-delivers no matter how many more
`Stop`/`sessionEnd` events fire.

## Files

- `detect.py` -- repo-root scoping, relevant-path filter, diff hashing,
  debounce/deliver state, the delivered instruction text
- `claude_stop_autopr.py` -- Claude `Stop` (debounced deliver, stderr + exit 2)
- `cursor_session.py` -- Cursor `stop` (silent) + `sessionEnd` (`followup_message`)
- `install_claude_hook.py` / `install_cursor_hook.py` -- merge, do not overwrite

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s hooks/auto-pr/tests -v
```
