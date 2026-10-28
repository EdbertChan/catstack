# fork-hook-skill-work

PreToolUse hook on Write / Edit / MultiEdit / NotebookEdit: exploring, fixing or
proving a hook or a skill runs in its own XIRP session, so the session the user
is steering keeps going. When a session that is not managed by XIRP edits
`engine/hooks/**`, `engine|corpus|product/skills/**`, `~/.claude/hooks/**` or
`~/.claude/skills/**`, the hook warns once per session and names the command:
`xirp session new --goal "<self-contained brief>" --new-branch <name>`.

XIRP sets `CHIRP_SESSION_ID` and `CHIRP_PROJECT_ID` in every session it manages;
the hook stays silent when both are set. Warn only, never stop: a denied tool
call can be final in a listening session.

Fail-open: a state directory that cannot be written is logged to stderr and the
warning still fires. State lives in `$CATSTACK_FORK_NUDGE_STATE_DIR` (default
`~/.cache/catstack-fork-hook-skill-work`).

## Files

- `detect.py` -- managed-session check, watched-path match, once-per-session state.
- `claude_pretooluse.py` -- Claude PreToolUse entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- fires outside a managed session, silent inside one.

Tests: `python3 -m unittest discover -s engine/hooks/fork-hook-skill-work/tests -v`
