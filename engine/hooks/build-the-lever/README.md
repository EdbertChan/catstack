# build-the-lever

Inject the existing `principle-build-the-lever` skill when the work is bulk
or the agent is hand-editing many files. The skill itself has
`disable-model-invocation: true`, so nothing loads it without a slash
command or this hook.

Fail-open. Its registry mode is `warn`, so it injects context without blocking.
Stays silent on one-file typo or "add a comment" asks. The shared hook runtime
applies the mode, renders each harness response, and writes one event row per
finding.

## Files

- `detect.py` — bulk-prompt and file-mutation detection returning SDK findings
- `state.py` — session cache under `~/.cache/catstack-build-the-lever`
- `claude_prompt_submit.py` / `claude_posttooluse.py` — thin Claude SDK entrypoints
- `cursor_before_submit.py` / `cursor_post_tool_use.py` — thin Cursor SDK entrypoints
  (`beforeSubmitPrompt` cannot inject; reminder arrives on first `postToolUse`)
- `codex_prompt_submit.py` / `codex_posttooluse.py` — thin Codex SDK entrypoints
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`

## Install

`./install.sh` from the catstack repo root, then restart Claude Code, Cursor,
and Codex (Codex also needs `/hooks` trust).

## Tests

```sh
python3 -m unittest discover -s engine/hooks/build-the-lever/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/build-the-lever
```
