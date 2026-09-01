# build-the-lever

Inject the existing `principle-build-the-lever` skill when the work is bulk
or the agent is hand-editing many files. The skill itself has
`disable-model-invocation: true`, so nothing loads it without a slash
command or this hook.

Fail-open. Inject-only. Never blocks tools. Stays silent on one-file typo
or "add a comment" asks.

## Files

- `detect.py` — bulk-prompt regex + per-session file-mutation count
- `state.py` — session cache under `~/.cache/catstack-build-the-lever`
- `claude_prompt_submit.py` / `claude_posttooluse.py` — Claude inject
- `cursor_before_submit.py` / `cursor_post_tool_use.py` — Cursor parity
  (`beforeSubmitPrompt` cannot inject; reminder arrives on first `postToolUse`)
- `codex_prompt_submit.py` / `codex_posttooluse.py` — Codex inject
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`

## Install

`./install.sh` from the catstack repo root, then restart Claude Code, Cursor,
and Codex (Codex also needs `/hooks` trust).

## Tests

```sh
python3 -m unittest discover -s engine/hooks/build-the-lever/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/build-the-lever
```
