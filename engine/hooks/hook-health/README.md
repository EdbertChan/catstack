# hook-health

`hook-health` is the non-blocking prompt hook that tells the agent about failed
catstack hook runs recorded by `_runner/run.py`. It is installed as
`UserPromptSubmit` for Claude and Codex, and as `beforeSubmitPrompt` for Cursor.

On each prompt it reads `~/.cache/catstack-hook-metrics/runs.jsonl` by default,
or `$CATSTACK_HOOK_METRICS_DIR/runs.jsonl` when that environment variable is
set. It starts at the byte offset stored in the current session's state file:

```text
hook-health-<harness>-<session>.json
```

The session value comes from `session_id`, then `conversation_id`, then
`unknown`; characters outside letters, digits, `_`, `.`, and `-` are replaced
with `_`. If the saved offset is past the end of the log, reading starts at the
beginning.

The notice appears only when new rows since that offset contain failures for
the current harness. Failure outcomes are `crashed`, `timed_out`, and
`caught_error`. Rows for `hook-health` itself are ignored. `spoke`, `silent`,
and `blocked` rows do not produce a notice. A missing log also stays silent
because no wrapped hook has written metrics yet.

The failure notice has this shape:

```text
hook-health: <count> hook run(s) failed since the last prompt: <hook>/<script> <outcome> (exit <exit_code>)[: <first stderr line>][; ...][; and <n> more] -- run python3 ~/.claude/hooks/_runner/report.py for the table.
```

At most five failed rows are named. If there are more than five, the notice ends
the row list with `and <n> more`. The stderr suffix uses the first non-empty
line from `stderr_tail`; it is omitted when there is no such line.

An unreadable metrics log emits this unchecked notice instead:

```text
hook-health: could not read the hook metrics log <path>: <error>; hook failures are unchecked this turn.
```

The hook never blocks prompt submission. Claude and Codex receive the notice as
`hookSpecificOutput.additionalContext`; Cursor receives it as
`additional_context` with `continue: true`. Malformed stdin and unexpected
runtime errors are written to stderr as `catstack-hook-error hook-health: ...`
and the hook exits zero.

## Files

- `detect.py` returns the notice from already-loaded rows.
- `runtime.py` owns the log offset and output shape.
- `claude_prompt_submit.py`, `cursor_before_submit.py`, `codex_prompt_submit.py` are non-blocking entrypoints.
- `*.hook.json` and `install_*_hook.py` merge the hook into the three harnesses.
- `tests/` covers failed rows, silent rows, self-ignore, truncation, one-shot offsets, and unreadable logs.
