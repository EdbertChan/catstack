# hook-health

UserPromptSubmit hook: hook failures recorded by `_runner/run.py` reach the
agent on the next prompt instead of sitting unread in
`~/.cache/catstack-hook-metrics/runs.jsonl`.

It reads the metrics log from a per-session byte offset, considers only new
rows for the current harness, ignores `hook-health` itself, and adds one
advisory context line for `crashed`, `timed_out`, and `caught_error` outcomes.
Missing logs stay silent because no wrapped hook has run yet. Unreadable logs
emit an unchecked notice. The hook never blocks and exits zero after caught
errors.

Fail direction: fail open. A missing log is silent, an unreadable log is
named as unchecked, and state write failures are caught by the entrypoint
wrapper.

There is no escape hatch. Run `python3 ~/.claude/hooks/_runner/report.py` for
the full table.

## Files

- `detect.py` returns the notice from already-loaded rows.
- `runtime.py` owns the log offset and output shape.
- `claude_prompt_submit.py`, `cursor_before_submit.py`, `codex_prompt_submit.py` are non-blocking entrypoints.
- `*.hook.json` and `install_*_hook.py` merge the hook into the three harnesses.
- `tests/` covers failed rows, silent rows, self-ignore, truncation, one-shot offsets, and unreadable logs.
