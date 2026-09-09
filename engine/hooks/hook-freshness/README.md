# hook-freshness

UserPromptSubmit hook: the installed hooks are only as new as the checkout
behind them. `install.sh` symlinks `~/.claude/hooks/<name>` at a catstack
checkout, so a hook or skill fix merged on `origin/main` does nothing on this
machine while that checkout sits on a feature branch or behind the remote.

Resolves the checkout from the `~/.claude/hooks/diu-stop` symlink (override
with `CATSTACK_HOOKS_REPO`), reads `git branch --show-current` and
`git rev-list --count HEAD..origin/main`, and adds one advisory line to the
turn's context when the checkout is off `main` or behind it. Once per
session, keyed by transcript path.

Advisory only — never blocks. No network by default; set
`CATSTACK_HOOK_FRESHNESS_FETCH=1` to allow a 3-second `git fetch` first, so
the count is not itself stale. `CATSTACK_HOOK_FRESHNESS=0` silences it.
Fails open on every error: no symlink, no git, a detached HEAD, a timeout.

## Files

- `detect.py` — checkout resolution, `repo_state()`, `advisory()`, `decide()`.
- `claude_prompt_submit.py` — Claude UserPromptSubmit entrypoint.
- `claude.prompt.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/test_hooks.py` — stale branch, behind count, clean checkout, fail-open.

## Env

| Var | Effect |
|-----|--------|
| `CATSTACK_HOOKS_REPO` | Use this checkout instead of resolving the symlink. |
| `CATSTACK_HOOK_FRESHNESS_FETCH=1` | Allow a short `git fetch origin main` first. |
| `CATSTACK_HOOK_FRESHNESS=0` | Silence the advisory. |
| `HOOK_FRESHNESS_STATE_DIR` | Once-per-session marker directory. |
