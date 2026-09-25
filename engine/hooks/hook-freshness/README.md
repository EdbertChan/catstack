# hook-freshness

UserPromptSubmit hook: the installed hooks are only as new as the checkout
behind them. `install.sh` symlinks `~/.claude/hooks/<name>` at a catstack
checkout, so a hook or skill fix merged on `origin/main` does nothing on this
machine while that checkout sits on a feature branch or behind the remote.

Resolves the checkout from the `~/.claude/hooks/diu-stop` symlink (override
with `CATSTACK_HOOKS_REPO`), reads `git branch --show-current` and
`git rev-list --count HEAD..origin/main`, and adds one advisory line to the
turn's context when the checkout is off `main` or behind it. It also reports
installed hook folders that no longer exist in that checkout. Once per
session, keyed by transcript path.

Being behind is advisory. An installed hook folder that is gone from the
checkout is a stop-mode rule in the shared registry. `CATSTACK_HOOK_FRESHNESS` picks the mode:
`local` (the default) compares against the last `origin/main` you fetched,
`fetch` first runs a 3-second `git fetch` so the count is not itself stale,
and `off` silences it.
Fails open on every error: no symlink, no git, a detached HEAD, a timeout.

## Files

- `detect.py` — checkout resolution, `repo_state()`, `advisory()`, `detect()`.
- `claude_prompt_submit.py` / `cursor_before_submit.py` / `codex_prompt_submit.py` — harness entrypoints through the shared hook runtime.
- `claude.prompt.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/test_hooks.py` — stale branch, behind count, clean checkout, fail-open.

## Env

| Var | Effect |
|-----|--------|
| `CATSTACK_HOOKS_REPO` | Use this checkout instead of resolving the symlink. |
| `CATSTACK_HOOK_FRESHNESS=local` | Default. Count against the local `origin/main`, no network. |
| `CATSTACK_HOOK_FRESHNESS=fetch` | Run a short `git fetch origin main` first. |
| `CATSTACK_HOOK_FRESHNESS=off` | Silence the advisory (`0` also works). |

`CATSTACK_HOOK_FRESHNESS_FETCH` is retired: the hook ignores it and says so
in its advisory. An unknown value falls back to `local` with a note.
| `HOOK_FRESHNESS_STATE_DIR` | Once-per-session marker directory. |
