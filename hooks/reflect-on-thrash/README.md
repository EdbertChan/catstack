# reflect-on-thrash

When `token_audit.py` flags real thrash (stuck retries, edits with no check,
user frustration, or 3+ identical re-reads), prompt the agent **once** to
run `reflect` in a subagent.

Not every session. Not a cheaper-model suggestion. Not a single accidental
re-read. Fail-open. A second Stop after the prompt is allowed so the extra
turn can finish.

## Files

- `detect.py` — shared gate, marker, transcript lookup
- `claude_stop_reflect.py` — Claude `Stop` (stderr + exit 2)
- `cursor_session.py` — Cursor `stop` + `sessionEnd` (`followup_message`)
- `install_claude_hook.py` / `install_cursor_hook.py` — merge, do not overwrite

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s hooks/reflect-on-thrash/tests -v
```
