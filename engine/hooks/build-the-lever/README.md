# build-the-lever

Inject the existing `principle-build-the-lever` skill when the work is bulk
or the agent is hand-editing many files. The skill itself has
`disable-model-invocation: true`, so nothing loads it without a slash
command or this hook.

Fail-open. Inject-only. Never blocks tools. Stays silent on one-file typo
or "add a comment" asks.

The shared registry keeps this hook in `warn` mode. Set
`CATSTACK_HOOK_MODE_BUILD_THE_LEVER=off|warn|stop` for a machine-local
override. Warnings use the `build-the-lever:` reminder text; detection or
metrics failures allow the harness action.

## Files

- `detect.py` — bulk-prompt/file-mutation detection returning SDK findings
- `state.py` — session cache under `~/.cache/catstack-build-the-lever`
- harness entry scripts — thin calls into `engine/hooks/_sdk/runtime.py`
- `cursor_before_submit.py` / `cursor_post_tool_use.py` — Cursor parity
  (`beforeSubmitPrompt` cannot inject; reminder arrives on first `postToolUse`)
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`

## Install

`./install.sh` from the catstack repo root, then restart Claude Code, Cursor,
and Codex (Codex also needs `/hooks` trust).

## Tests

```sh
python3 -m unittest discover -s engine/hooks/build-the-lever/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/build-the-lever
```
