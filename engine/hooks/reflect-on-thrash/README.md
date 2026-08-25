# reflect-on-thrash

When `token_audit.py` flags real thrash (stuck retries, edits with no check,
user frustration, or 3+ identical re-reads), **defer** a reflect prompt. Do
not steal the current turn.

Cursor `stop` and Claude `Stop` only write a deferred marker. Cursor
`sessionEnd` delivers the prompt once, after the session is over. Claude
does not force an extra Stop turn. Fail-open.

Not every session. Not a cheaper-model suggestion. Not a single accidental
re-read.

## Files

- `detect.py` — shared gate, deferred vs prompted markers, transcript lookup
- `claude_stop_reflect.py` — Claude `Stop` (defer only, exit 0)
- `cursor_session.py` — Cursor `stop` (silent) + `sessionEnd` (`followup_message`)
- `install_claude_hook.py` / `install_cursor_hook.py` — merge, do not overwrite

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s hooks/reflect-on-thrash/tests -v
```
